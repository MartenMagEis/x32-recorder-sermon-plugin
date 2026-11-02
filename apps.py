import threading

from django.apps import AppConfig

from recorder.plugin_support import should_start_background_work


class ServicePluginConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Must match the folder name this repo gets cloned into by x32-recorder's plugin system
    # (derived from the GitHub URL) - "x32-recorder-sermon-plugin" -> "x32_recorder_sermon_plugin".
    name = "x32_recorder_sermon_plugin"
    verbose_name = "Gottesdienst-Aufnahme"

    def ready(self):
        if not should_start_background_work():
            return
        from .service import run_service

        threading.Thread(target=run_service, daemon=True, name="sermon-schedule").start()
