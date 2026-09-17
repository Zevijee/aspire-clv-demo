"""Compatibility entrypoint. Launch the application through api.main."""

from api.main import app, create_app, get_health

__all__ = ["app", "create_app", "get_health"]
