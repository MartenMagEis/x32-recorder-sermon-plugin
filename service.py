"""The running part: a background thread in the x32-recorder web process (started by apps.py) that
starts the recording on schedule and ends it again - after the maximum length, or when it stays
quiet around the usual end. The console being switched off ends a recording anyway: the controller
stops it once no more audio arrives; this side then only marks where the quiet began.

Starting and stopping go through x32-recorder's REST API (start_from_template, stop) - the same
paths the web UI, voice control and the console buttons use, so all validation stays in one place.
Levels come from the controller's ChannelLevel table (peak-hold dBFS, written every ~0.5 s while
recording), no audio of its own.
"""
import datetime
import json
import logging
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from django.db import close_old_connections
from django.utils import timezone

from . import schedule

logger = logging.getLogger(__name__)

LOOP_S = 2.0
LEVEL_STALE_S = 5.0  # an older level reading means no audio is arriving any more
QUIET_MARKER_NAME = "Stille ab hier"
CLOCK_CHECK_S = 60.0
START_RETRY_S = 30.0  # a failed start (console still off, ...) is retried within the start window


def _clock_synchronized():
    """True if the system clock is set from the network. A Pi has no real-time clock: after a power
    cut without internet it may run on an old time, and a schedule then fires at the wrong moment.
    Where timedatectl doesn't exist (not Linux), the clock is taken as right."""
    if not sys.platform.startswith("linux"):
        return True
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return out != "no"


class ServiceRunner:
    def __init__(self, api=None, now=None, clock_ok=None):
        self._api_call = api or self._http_api
        self._now = now or timezone.localtime
        self._clock_ok = clock_ok or _clock_synchronized
        self._clock_state = (0.0, True)
        self.tracker = schedule.QuietTracker()
        self.tracked_id = None
        self.status = "startet"
        self.warnings = []
        self._last_attempt = None

    # --- recorder API ------------------------------------------------------------------------

    def _http_api(self, method, path, data=None):
        from recorder.models import RecorderSettings

        port = RecorderSettings.get_solo().web_port or 8000
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api{path}",
                                     data=json.dumps(data or {}).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                detail = ""
            raise RuntimeError(detail or f"HTTP {e.code}") from e

    def clock_ok(self):
        checked_at, ok = self._clock_state
        if time.monotonic() - checked_at > CLOCK_CHECK_S or checked_at == 0.0:
            ok = self._clock_ok()
            self._clock_state = (time.monotonic(), ok)
        return ok

    # --- one pass ----------------------------------------------------------------------------

    def tick(self):
        from recorder.models import Recording

        from .models import AutoRecording, ServiceSettings

        close_old_connections()
        settings = ServiceSettings.get_solo()
        now = self._now()
        warnings = []
        watched = AutoRecording.objects.filter(stop_reason="").select_related("recording").first()

        if watched is not None:
            self._watch(settings, watched, now)
        elif not settings.enabled:
            self.status = "aus"
        else:
            if settings.template_id is None:
                warnings.append("Gottesdienst-Aufnahme: keine Vorlage gewählt - es wird nicht automatisch aufgenommen.")
            clock_ok = self.clock_ok()
            if not clock_ok:
                warnings.append("Gottesdienst-Aufnahme: Die Uhrzeit des Recorders ist nicht mit dem Internet "
                                "abgeglichen - die automatische Aufnahme startet erst, wenn sie stimmt.")
            weekdays = schedule.parse_weekdays(settings.weekdays)
            start_time = schedule.parse_time(settings.start_time)
            due = schedule.start_due(now, weekdays, start_time, settings.last_start_date)
            retry_wait = self._last_attempt is not None and time.monotonic() - self._last_attempt < START_RETRY_S
            if due and clock_ok and settings.template_id is not None and not retry_wait:
                self._start(settings, due, Recording)
            elif due and retry_wait:
                pass  # keep the failure message in the status until the next try
            else:
                upcoming = schedule.next_start(now, weekdays, start_time, settings.last_start_date)
                self.status = ("bereit - nächster Start " + _format(upcoming)) if upcoming else "bereit"
        self.warnings = warnings

    def _start(self, settings, due, Recording):
        from .models import AutoRecording

        self._last_attempt = time.monotonic()
        active = Recording.objects.exclude(state=Recording.STOPPED).first()
        if active is not None:
            # Someone started (or is playing back) already - a recording with our template is
            # taken over and ended automatically like our own, anything else is left alone.
            if active.state in (Recording.NEW, Recording.RECORD) and active.template_id == settings.template_id:
                AutoRecording.objects.create(recording=active)
                self.status = f"Aufnahme übernommen: {active.name or active.id}"
            else:
                self.status = f"Start {_format(due)} übersprungen - es lief schon eine Aufnahme/Wiedergabe"
            logger.info(self.status)
            self._done_for_today(settings, due)
            return
        try:
            rec = self._api_call("POST", "/recordings/start_from_template/", {"template_id": settings.template_id})
        except Exception as e:
            self.status = f"Start {_format(due)} fehlgeschlagen, neuer Versuch in 30 s: {e}"
            logger.warning(self.status)
            return
        self._done_for_today(settings, due)
        AutoRecording.objects.create(recording_id=rec["id"])
        self.tracker = schedule.QuietTracker()
        self.tracked_id = rec["id"]
        self.status = f"Aufnahme gestartet: {rec.get('name') or rec['id']}"
        logger.info(self.status)

    def _done_for_today(self, settings, due):
        self._last_attempt = None
        settings.last_start_date = due.date()
        settings.save(update_fields=["last_start_date"])

    def _watch(self, settings, watched, now):
        from recorder.models import Recording

        recording = Recording.objects.get(pk=watched.recording_id)
        if self.tracked_id != recording.id:  # e.g. after a restart of the web process
            self.tracker = schedule.QuietTracker()
            self.tracked_id = recording.id
        if recording.state in (Recording.NEW, Recording.RECORD) and recording.started_at is None:
            self.status = "Aufnahme startet ..."
            return

        if recording.state != Recording.RECORD:
            # Ended without us: by hand, or by the controller because no more audio came (console
            # switched off). Then mark where it went quiet, if it did.
            if recording.state == Recording.STOPPED:
                self._mark_quiet(watched, recording)
                watched.stop_reason = "extern"
                watched.save(update_fields=["stop_reason"])
                self.status = "Aufnahme beendet (von Hand oder Gerät aus)"
                logger.info(self.status)
            return

        elapsed = now - recording.started_at
        loud = self._loud(recording, settings.quiet_threshold_db, now)
        quiet_since = self.tracker.feed(elapsed, loud)
        reason = schedule.stop_reason(
            elapsed, quiet_since,
            normal=datetime.timedelta(minutes=settings.normal_minutes),
            tolerance=datetime.timedelta(minutes=settings.tolerance_minutes),
            maximum=datetime.timedelta(minutes=settings.max_minutes),
            quiet_needed=datetime.timedelta(minutes=settings.quiet_minutes),
        )
        if reason is None:
            quiet = f", still seit {_minutes(elapsed - quiet_since)}" if quiet_since is not None else ""
            self.status = f"Aufnahme läuft ({_minutes(elapsed)}{quiet})"
            return
        self._mark_quiet(watched, recording)
        try:
            self._api_call("POST", f"/recordings/{recording.id}/stop/")
        except Exception as e:
            self.status = f"Beenden fehlgeschlagen: {e}"
            logger.warning(self.status)
            return
        watched.stop_reason = reason
        watched.save(update_fields=["stop_reason"])
        self.status = ("Aufnahme nach Stille beendet" if reason == schedule.STOP_QUIET
                       else "Aufnahme nach maximaler Länge beendet")
        logger.info(self.status)

    def _loud(self, recording, threshold_db, now):
        """Any watched channel above the threshold in a fresh reading. Watched are the recording's
        Master channels if it has any (the whole service in one), else all of its channels."""
        from recorder.models import ChannelLevel

        channels = recording.master_channels or recording.channels or []
        fresh_after = now - datetime.timedelta(seconds=LEVEL_STALE_S)
        return ChannelLevel.objects.filter(
            channel_no__in=[c + 1 for c in channels], updated_at__gte=fresh_after, peak_dbfs__gte=threshold_db,
        ).exists()

    def _mark_quiet(self, watched, recording):
        from recorder.models import RecordingMarker

        quiet_since = self.tracker.quiet_since
        if quiet_since is None or watched.quiet_marker_set or self.tracked_id != recording.id:
            return
        RecordingMarker.objects.create(recording=recording, timestamp=quiet_since,
                                       marker_type=RecordingMarker.TYPE_SPECIAL, name=QUIET_MARKER_NAME)
        watched.quiet_marker_set = True
        watched.save(update_fields=["quiet_marker_set"])

    def run(self):
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception("service loop error")
                time.sleep(5)
            time.sleep(LOOP_S)


def _format(moment):
    if moment is None:
        return "-"
    return f"{schedule.WEEKDAY_NAMES[moment.weekday()]} {moment:%d.%m. %H:%M}"


def _minutes(delta):
    total = int(delta.total_seconds() // 60)
    return f"{total // 60}:{total % 60:02d} h"


_runner = None
_lock = threading.Lock()


def get_runner():
    global _runner
    with _lock:
        if _runner is None:
            _runner = ServiceRunner()
    return _runner


def run_service():
    get_runner().run()
