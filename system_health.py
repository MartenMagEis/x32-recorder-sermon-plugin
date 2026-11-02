"""Warnings for x32-recorder's banner (system_health.py plugin convention) - e.g. a clock that
isn't synchronized, which would make the schedule fire at the wrong time."""
from .service import get_runner


def get_warnings():
    return [{"key": f"sermon_{i}", "message": m} for i, m in enumerate(get_runner().warnings)]
