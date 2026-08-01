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

    # Web Push (VAPID). Leave these unset to keep browser push delivery off
    # while in-app notifications continue to work.
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")

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
