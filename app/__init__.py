"""Application factory: builds and configures the Flask + Socket.IO app."""
import os

from flask import Flask, g, url_for

from config import INSTANCE_DIR, load_config

from .csrf import init_csrf
from .errors import register_error_handlers
from .extensions import db, socketio
from .models import (
    ANNOUNCEMENT_CONTENT_MAX, ANNOUNCEMENT_TITLE_MAX, CATEGORIES, DESCRIPTION_MAX, MESSAGE_MAX,
    PRIORITIES, ROLES, STATUS_TRANSITIONS, STATUSES, TITLE_MAX, WORKSTATION_MAX, isoformat,
)
from .services import stats


def create_app(config_overrides=None):
    app = Flask(__name__, instance_path=str(INSTANCE_DIR))
    app.config.update(load_config(config_overrides))
    INSTANCE_DIR.mkdir(exist_ok=True)

    db.init_app(app)
    # Import the Socket.IO event handlers *before* init_app(): Flask-SocketIO
    # only remembers handlers registered before its server exists.
    from . import sockets  # noqa: F401
    # async_mode="threading": one OS thread per connection, served by Werkzeug.
    # With the simple-websocket package installed this supports real WebSockets.
    socketio.init_app(
        app,
        async_mode="threading",
        ping_interval=app.config["SOCKETIO_PING_INTERVAL"],
        ping_timeout=app.config["SOCKETIO_PING_TIMEOUT"],
    )

    init_csrf(app)
    register_error_handlers(app)
    _register_blueprints(app)
    _register_template_helpers(app)

    from .cli import register_cli
    register_cli(app)

    with app.app_context():
        db.create_all()  # creates missing tables only; never drops data
    return app


def _register_blueprints(app):
    from .api import bp as api_bp
    from .assistant import bp as assistant_bp
    from .auth import bp as auth_bp
    from .student import bp as student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(api_bp)


def _initials(name):
    parts = name.split()
    return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper()


def _register_template_helpers(app):
    app.jinja_env.filters["iso"] = isoformat
    app.jinja_env.filters["display_time"] = (
        lambda value: value.strftime("%d %b %Y, %H:%M UTC") if value else ""
    )
    app.jinja_env.filters["initials"] = _initials

    def static_url(filename):
        """URL of a static file with its modification time appended, so browsers
        fetch the new version after an update instead of a stale cached copy."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals["static_url"] = static_url

    def nav_stats():
        """Counts for the sidebar badges, computed once per request when needed."""
        if "nav_stats" not in g:
            g.nav_stats = stats.stats_for(g.user) if g.get("user") else {}
        return g.nav_stats

    @app.context_processor
    def inject_choices():
        user = g.get("user")
        return {
            "nav_stats": nav_stats,
            "CATEGORIES": CATEGORIES,
            "PRIORITIES": PRIORITIES,
            "STATUSES": STATUSES,
            "ROLES": ROLES,
            "LIMITS": {
                "title": TITLE_MAX, "description": DESCRIPTION_MAX,
                "workstation": WORKSTATION_MAX, "message": MESSAGE_MAX,
                "announcement_title": ANNOUNCEMENT_TITLE_MAX,
                "announcement_content": ANNOUNCEMENT_CONTENT_MAX,
            },
            # Read by the JavaScript (labels, current user); contains no secrets.
            "client_config": {
                "user": user.to_public_dict() if user else None,
                "labels": {"categories": CATEGORIES, "priorities": PRIORITIES,
                           "statuses": STATUSES},
                "transitions": STATUS_TRANSITIONS,
            },
        }
