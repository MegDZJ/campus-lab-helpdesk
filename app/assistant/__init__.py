from flask import Blueprint

bp = Blueprint("assistant", __name__, url_prefix="/assistant")

from . import routes  # noqa: E402,F401  (registers the routes on bp)
