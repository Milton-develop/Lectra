"""Application configuration.

Environment variables are loaded from the .env file (see .env.example).
No secrets are hardcoded anywhere in the project.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration loaded from environment variables."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Supabase (PostgreSQL backend)
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    # OneSignal (browser push). Leave these unset to keep push delivery off
    # while in-app notifications continue to work. Pushes are scheduled with
    # send_after so OneSignal delivers them even when the web service sleeps.
    ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "")
    ONESIGNAL_REST_API_KEY = os.getenv("ONESIGNAL_REST_API_KEY", "")

    # Accounts whose email is in this comma-separated list are promoted to
    # admin on sign-in (they can post and manage the defence roster). The very
    # first account ever created also becomes admin automatically.
    ADMIN_EMAILS = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }

    # JSON API
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False


class DevelopmentConfig(Config):
    DEBUG = True
    # Fallback so the app runs out-of-the-box during development. Always set a
    # real SECRET_KEY in .env for any shared/production deployment.
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-secret-key"


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


def get_config():
    """Return the config class appropriate for the current environment.

    Defaults to development unless FLASK_ENV is set to 'production'.
    """
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
