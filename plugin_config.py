"""Settings on x32-recorder's Settings page (plugin_config.py convention)."""
from recorder.models import RecordingTemplate
from recorder.plugin_support import describe_model_fields, model_instance_values

from .models import ServiceSettings
from .service import get_runner

FIELDS = ["enabled", "weekdays", "start_time", "normal_minutes", "tolerance_minutes", "max_minutes",
          "quiet_minutes", "quiet_threshold_db"]


def get_config_schema():
    fields = describe_model_fields(ServiceSettings, FIELDS)
    template_field = ServiceSettings._meta.get_field("template")
    fields.insert(1, {
        "name": "template", "label": template_field.verbose_name, "type": "choice",
        "help_text": template_field.help_text, "readonly": False,
        "choices": [["", "– keine –"]] + [[t.id, t.name] for t in RecordingTemplate.objects.order_by("name")],
    })
    fields.append({"name": "status", "label": "Status", "type": "string", "help_text": "", "readonly": True})
    return {"fields": fields}


def get_config_values():
    settings = ServiceSettings.get_solo()
    values = model_instance_values(settings, FIELDS)
    values["template"] = settings.template_id or ""
    runner = get_runner()
    values["status"] = runner.status + "".join(f"\n{w}" for w in runner.warnings)
    return values


def update_config_values(data):
    settings = ServiceSettings.get_solo()
    for key, value in data.items():
        if key in FIELDS:
            setattr(settings, key, value)
    if "template" in data:
        settings.template_id = int(data["template"]) if data["template"] not in (None, "") else None
    settings.full_clean()
    settings.save()
    return get_config_values()
