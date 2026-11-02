from django.core.exceptions import ValidationError
from django.db import models

from . import schedule


class ServiceSettings(models.Model):
    """App-wide settings (one row), edited on x32-recorder's Settings page (plugin_config.py)."""

    enabled = models.BooleanField(
        "Automatisch aufnehmen", default=False,
        help_text="Startet die Aufnahme nach Wochenplan und beendet sie automatisch."
    )
    template = models.ForeignKey(
        "recorder.RecordingTemplate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name="Vorlage",
        help_text="Kanäle, Gerät und Name der Aufnahme kommen aus dieser Vorlage - wie bei einem Start "
                   "in der Weboberfläche."
    )
    weekdays = models.CharField(
        "Wochentage", max_length=40, default="So",
        help_text="Z.B. 'So' oder 'Sa, So'."
    )
    start_time = models.CharField(
        "Startzeit", max_length=5, default="10:28",
        help_text="HH:MM. Gestartet wird nur bis 20 Minuten danach - ein Pi, der erst später "
                   "hochfährt, nimmt diesen Termin nicht mehr auf."
    )
    normal_minutes = models.IntegerField(
        "Normale Länge (min)", default=75,
        help_text="So lange dauert ein Gottesdienst üblicherweise."
    )
    tolerance_minutes = models.IntegerField(
        "Früheste Stille vor der normalen Länge (min)", default=15,
        help_text="Erst ab 'normale Länge minus diesem Wert' kann Stille die Aufnahme beenden - eine "
                   "lange Pause mittendrin beendet sie nicht."
    )
    max_minutes = models.IntegerField(
        "Maximale Länge (min)", default=120,
        help_text="Spätestens dann wird die Aufnahme beendet."
    )
    quiet_minutes = models.IntegerField(
        "Stille bis zum Ende (min)", default=7,
        help_text="So lange muss es durchgehend still sein, bevor die Aufnahme endet."
    )
    quiet_threshold_db = models.IntegerField(
        "Stille unter (dBFS)", default=-50,
        help_text="Pegel, unter dem es als still gilt (Spitzenwert über die überwachten Kanäle)."
    )
    # The planned start already made today - so one day never gets two automatic starts.
    last_start_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Gottesdienst-Aufnahme"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        try:
            schedule.parse_weekdays(self.weekdays)
            schedule.parse_time(self.start_time)
        except ValueError as e:
            raise ValidationError(str(e))
        if self.max_minutes <= self.normal_minutes:
            raise ValidationError("Die maximale Länge muss größer sein als die normale Länge.")
        if not 0 <= self.tolerance_minutes < self.normal_minutes:
            raise ValidationError("'Früheste Stille' muss kleiner als die normale Länge sein.")
        if self.quiet_minutes < 1:
            raise ValidationError("Die Stille bis zum Ende muss mindestens 1 Minute sein.")
        if self.enabled and self.template_id is None:
            raise ValidationError("Bitte eine Vorlage wählen.")


class AutoRecording(models.Model):
    """A recording this plugin started (or took over) and watches until it ends."""

    recording = models.OneToOneField("recorder.Recording", on_delete=models.CASCADE, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True)
    # "" while watched; afterwards why it ended: schedule.STOP_MAX / STOP_QUIET / "extern"
    stop_reason = models.CharField(max_length=20, blank=True, default="")
    quiet_marker_set = models.BooleanField(default=False)
