"""Access-control helpers used by the page and API blueprints."""
from functools import wraps

from flask import g, redirect, request, url_for

from ..errors import NotAuthenticated, PermissionDenied, is_api_request
from ..models import ROLES


def _login_redirect():
    if is_api_request():
        raise NotAuthenticated("Please log in to continue.")
    return redirect(url_for("auth.login", next=request.path))


def enforce_role(*roles):
    """Return a redirect/raise if the current user lacks one of ``roles``.

    Returns None when access is allowed, so it can be used directly in a
    blueprint's before_request hook to protect every route in that blueprint.
    """
    if g.user is None:
        return _login_redirect()
    if roles and g.user.role not in roles:
        allowed = " or ".join(ROLES[role] for role in roles)
        raise PermissionDenied(f"This area is only available to: {allowed}.")
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        return enforce_role() or view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            return enforce_role(*roles) or view(*args, **kwargs)
        return wrapped
    return decorator
