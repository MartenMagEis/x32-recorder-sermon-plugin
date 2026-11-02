"""Django-side tests - run inside an x32-recorder checkout with this plugin enabled:

    uv run python x32recorder/manage.py test x32_recorder_sermon_plugin
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from recorder.models import ChannelLevel, Recording, RecordingMarker, RecordingTemplate

from ..models import AutoRecording, ServiceSettings
from ..service import QUIET_MARKER_NAME, ServiceRunner

SUNDAY_10_28 = timezone.make_aware(datetime.datetime(2026, 11, 8, 10, 28))


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


class RunnerTests(TestCase):
    def setUp(self):
        self.template = RecordingTemplate.objects.create(name="Gottesdienst", channel_count=2)
        settings = ServiceSettings.get_solo()
        settings.enabled = True
        settings.template = self.template
        settings.save()
        self.clock = Clock(SUNDAY_10_28)
        self.calls = []
        self.runner = ServiceRunner(api=self.api, now=self.clock, clock_ok=lambda: True)

    def api(self, method, path, data=None):
        self.calls.append((method, path))
        if path == "/recordings/start_from_template/":
            rec = Recording.objects.create(state=Recording.RECORD, channels=[0, 1], master_channels=[1],
                                           template=self.template, started_at=self.clock.now)
            return {"id": rec.id, "name": "Gottesdienst"}
        if path.endswith("/stop/"):
            Recording.objects.filter(pk=int(path.split("/")[2])).update(state=Recording.STOPPED)
        return {}

    def level(self, channel_no, dbfs):
        ChannelLevel.objects.update_or_create(channel_no=channel_no, defaults={"peak_dbfs": dbfs, "clipped": False})
        # updated_at is auto_now (real time); the runner compares against the fake clock
        ChannelLevel.objects.filter(channel_no=channel_no).update(updated_at=self.clock.now)

    def advance(self, minutes, dbfs=None):
        """Advance minute by minute; dbfs: master level during that time (None: no fresh reading)."""
        for _ in range(minutes):
            self.clock.now += datetime.timedelta(minutes=1)
            if dbfs is not None:
                self.level(2, dbfs)
            self.runner.tick()

    def test_starts_once_on_schedule(self):
        self.clock.now -= datetime.timedelta(minutes=1)
        self.runner.tick()
        self.assertEqual(self.calls, [])
        self.clock.now += datetime.timedelta(minutes=1)
        self.runner.tick()
        self.assertEqual(self.calls, [("POST", "/recordings/start_from_template/")])
        self.assertEqual(AutoRecording.objects.count(), 1)

    def test_pause_mid_service_does_not_stop_but_quiet_at_the_end_does(self):
        self.runner.tick()
        self.advance(40, dbfs=-20)
        self.advance(12, dbfs=-70)  # a long, quiet stretch halfway through
        self.advance(20, dbfs=-20)
        self.assertFalse(any(p.endswith("/stop/") for _, p in self.calls))
        self.advance(8, dbfs=-70)
        stops = [p for _, p in self.calls if p.endswith("/stop/")]
        self.assertEqual(len(stops), 1)
        marker = RecordingMarker.objects.get(name=QUIET_MARKER_NAME)
        self.assertEqual(marker.timestamp, datetime.timedelta(minutes=73))
        self.assertEqual(AutoRecording.objects.get().stop_reason, "quiet")

    def test_maximum_length(self):
        self.runner.tick()
        self.advance(121, dbfs=-20)
        self.assertEqual(AutoRecording.objects.get().stop_reason, "max")
        self.assertFalse(RecordingMarker.objects.exists())

    def test_console_switched_off_marks_where_audio_ended(self):
        self.runner.tick()
        self.advance(70, dbfs=-20)
        self.advance(2)  # no fresh level readings any more
        rec = Recording.objects.get()
        rec.state = Recording.STOPPED  # the controller stops a recording without audio by itself
        rec.save()
        self.advance(1)
        self.assertEqual(AutoRecording.objects.get().stop_reason, "extern")
        self.assertEqual(RecordingMarker.objects.get().timestamp, datetime.timedelta(minutes=71))

    def test_takes_over_a_recording_started_by_hand_with_the_template(self):
        Recording.objects.create(state=Recording.RECORD, channels=[0], template=self.template,
                                 started_at=self.clock.now - datetime.timedelta(minutes=3))
        self.runner.tick()
        self.assertEqual(self.calls, [])
        self.assertEqual(AutoRecording.objects.count(), 1)

    def test_no_start_with_an_unsynchronized_clock(self):
        runner = ServiceRunner(api=self.api, now=self.clock, clock_ok=lambda: False)
        runner.tick()
        self.assertEqual(self.calls, [])
        self.assertTrue(any("Uhrzeit" in w for w in runner.warnings))

    def test_failed_start_is_retried_in_the_window(self):
        def failing(method, path, data=None):
            self.calls.append(path)
            raise RuntimeError("Kein Audiogerät")
        runner = ServiceRunner(api=failing, now=self.clock, clock_ok=lambda: True)
        runner.tick()
        runner.tick()
        self.assertEqual(len(self.calls), 1)  # not again right away
        runner._last_attempt -= 31
        runner.tick()
        self.assertEqual(len(self.calls), 2)
        self.assertIsNone(ServiceSettings.get_solo().last_start_date)


class ConfigTests(TestCase):
    def test_schema_and_validation(self):
        from django.core.exceptions import ValidationError

        from .. import plugin_config

        RecordingTemplate.objects.create(name="Gottesdienst", channel_count=2)
        fields = {f["name"]: f for f in plugin_config.get_config_schema()["fields"]}
        self.assertEqual(fields["template"]["type"], "choice")
        self.assertIn("Gottesdienst", [c[1] for c in fields["template"]["choices"]])
        with self.assertRaises(ValidationError):
            plugin_config.update_config_values({"start_time": "10.28"})
        with self.assertRaises(ValidationError):
            plugin_config.update_config_values({"enabled": True})  # no template
        with self.assertRaises(ValidationError):
            plugin_config.update_config_values({"normal_minutes": 130})  # longer than the maximum
