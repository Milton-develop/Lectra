"""Lectra application entry point.

Run locally:        flask run
Run in production:  gunicorn app:app
"""

import time
from datetime import date, datetime, timezone
from threading import Thread
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import Flask, g, send_from_directory

from config import get_config
from routes import bp, inject_globals


def _start_reminder_scheduler(interval=60):
    """Deliver due reminders periodically so they fire even while nobody is
    browsing. Idempotent (the ``notification_sent`` flag prevents duplicates),
    so it is safe alongside the per-request check in ``routes._check_due_reminders``
    and with multiple WSGI workers."""

    def run():
        import models
        while True:
            try:
                models.process_all_due_reminders()
            except Exception:
                pass
            time.sleep(interval)

    Thread(target=run, daemon=True, name="reminder-scheduler").start()


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    app.register_blueprint(bp)
    app.context_processor(inject_globals)

    register_template_filters(app)
    register_root_files(app)
    register_commands(app)

    _start_reminder_scheduler()

    return app


def register_root_files(app):
    """Serve the PWA files from the project root so the service worker has
    root scope (required for offline caching of the whole app)."""

    @app.route("/manifest.json")
    def manifest():
        return send_from_directory(
            app.root_path, "manifest.json",
            mimetype="application/manifest+json",
        )

    @app.route("/service-worker.js")
    def service_worker():
        return send_from_directory(
            app.root_path, "service-worker.js",
            mimetype="application/javascript",
        )


def register_commands(app):
    """Commands intended to be run by a scheduler, not a web request."""

    @app.cli.command("send-reminders")
    def send_reminders():
        """Create and deliver all reminders that are currently due."""
        import models
        count = models.process_all_due_reminders()
        click.echo(f"Processed {count} due reminder(s).")


def _template_timezone():
    """The timezone the logged-in user selected in Profile settings."""
    settings = getattr(g, "settings", None) or {}
    tz_name = settings.get("timezone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def register_template_filters(app):
    @app.template_filter("fmt_date")
    def fmt_date(value, fmt="%b %d, %Y"):
        if not value:
            return ""
        try:
            if isinstance(value, str):
                value = date.fromisoformat(value[:10])
            return value.strftime(fmt)
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter("fmt_time")
    def fmt_time(value):
        if not value:
            return ""
        try:
            if isinstance(value, str):
                value = datetime.strptime(value[:5], "%H:%M")
            return value.strftime("%I:%M %p")
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter("fmt_datetime")
    def fmt_datetime(value):
        if not value:
            return ""
        try:
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(_template_timezone()).strftime("%b %d, %Y %I:%M %p")
        except (ValueError, TypeError):
            return str(value)


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
