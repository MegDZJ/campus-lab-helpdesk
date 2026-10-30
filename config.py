"""Application configuration.

Every setting can be overridden with an environment variable (see .env.example).
Values are read when the application is created, so a .env file loaded by
run.py or seed_demo.py is taken into account.
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
SECRET_KEY_FILE = INSTANCE_DIR / ".secret_key"


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value and value.strip() else default


def _development_secret_key():
    """Return a random secret key stored in instance/.secret_key.

    Used only when SECRET_KEY is not set in the environment. Keeping the key in
    a file (excluded from git) means login sessions survive a server restart.
    """
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
    INSTANCE_DIR.mkdir(exist_ok=True)
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key, encoding="utf-8")
    return key


def load_config(overrides=None):
    """Build the Flask configuration dictionary.

    ``overrides`` (used by the tests) take priority over environment values.
    """
    overrides = overrides or {}
    default_db = f"sqlite:///{(INSTANCE_DIR / 'helpdesk.db').as_posix()}"

    config = {
        # Network binding: 0.0.0.0 = listen on every network interface (LAN + localhost).
        "HOST": os.environ.get("HOST", "0.0.0.0"),
        "PORT": _env_int("PORT", 5000),
        "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL", default_db),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        # Session cookie: not readable from JavaScript, not sent on cross-site POSTs.
        "SESSION_COOKIE_NAME": "helpdesk_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # The lab LAN uses plain HTTP, so "Secure" cookies would never be sent.
        # Set SESSION_COOKIE_SECURE=1 only if you put the app behind HTTPS.
        "SESSION_COOKIE_SECURE": _env_bool("SESSION_COOKIE_SECURE", False),
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=_env_int("SESSION_HOURS", 8)),
        # Reject request bodies larger than 64 KB.
        "MAX_CONTENT_LENGTH": 64 * 1024,
        "CSRF_ENABLED": True,
        # Socket.IO heartbeat: the server pings every client every N seconds and
        # drops it if no reply arrives within the timeout.
        "SOCKETIO_PING_INTERVAL": _env_int("SOCKETIO_PING_INTERVAL", 10),
        "SOCKETIO_PING_TIMEOUT": _env_int("SOCKETIO_PING_TIMEOUT", 10),
        "SHOW_DEMO_CREDENTIALS": _env_bool("SHOW_DEMO_CREDENTIALS", False),
    }
    config.update(overrides)

    if not config.get("SECRET_KEY"):
        env_key = os.environ.get("SECRET_KEY")
        config["SECRET_KEY"] = env_key or _development_secret_key()
        config["SECRET_KEY_FROM_ENV"] = bool(env_key)
    return config
