"""Minimal CSRF protection.

A random token is kept in the user's session. Every state-changing request
(POST, PUT, PATCH, DELETE) must send it back, either as a hidden form field
called ``csrf_token`` or in the ``X-CSRF-Token`` header (used by fetch()).
Another website can make the browser send our cookie, but it cannot read the
token, so its forged requests are rejected.
"""
import secrets

from flask import current_app, request, session

from .errors import ValidationError

SESSION_KEY = "_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_csrf_token():
    token = session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_KEY] = token
    return token


def init_csrf(app):
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    @app.before_request
    def check_csrf_token():
        if request.method in SAFE_METHODS or not current_app.config.get("CSRF_ENABLED", True):
            return
        expected = session.get(SESSION_KEY)
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not expected or not sent or not secrets.compare_digest(expected, sent):
            raise ValidationError(
                "Your session's security token is missing or has expired. "
                "Reload the page and try again."
            )
