"""Login, logout and loading the current user for every request."""
import logging
import secrets

from flask import flash, g, redirect, render_template, request, session, url_for
from flask_socketio import disconnect

from ..extensions import db
from ..models import User
from ..presence import presence
from . import bp

log = logging.getLogger("helpdesk")


def home_url(user):
    return url_for("assistant.dashboard" if user.is_assistant else "student.dashboard")


def _safe_next(target):
    """Only follow ?next= links that stay on this site (no open redirect)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None


@bp.route("/")
def index():
    if g.user is None:
        return redirect(url_for("auth.login"))
    return redirect(home_url(g.user))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(home_url(g.user))

    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first() if username else None
        if user is None or not user.check_password(password):
            error = "Incorrect username or password."
            log.info("login    failed for '%s' from %s", username, request.remote_addr)
        else:
            session.clear()  # new session on login (prevents session fixation)
            session["user_id"] = user.id
            session["login_id"] = secrets.token_hex(8)
            session.permanent = True
            log.info("login    %s (%s) from %s", user.username, user.role, request.remote_addr)
            return redirect(_safe_next(request.args.get("next")) or home_url(user))

    status = 401 if error else 200
    return render_template("login.html", error=error, username=username), status


@bp.route("/logout", methods=["POST"])
def logout():
    # Close this browser session's live Socket.IO connections (other tabs too).
    for sid in presence.sids_for_login(session.get("login_id")):
        disconnect(sid=sid, namespace="/")
    if g.user is not None:
        log.info("logout   %s", g.user.username)
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
