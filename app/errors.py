"""Application exceptions and the handlers that turn them into responses.

Services raise these exceptions; API routes answer with JSON, page routes
render an error page, and Socket.IO handlers return them in the ack.
"""
from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException


class AppError(Exception):
    status_code = 400

    def __init__(self, message, fields=None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}

    def to_dict(self):
        return {"message": self.message, "fields": self.fields}


class ValidationError(AppError):
    status_code = 400


class NotAuthenticated(AppError):
    status_code = 401


class PermissionDenied(AppError):
    status_code = 403


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    """The request is valid but not allowed in the record's current state."""

    status_code = 409


def is_api_request():
    return request.path.startswith("/api/")


def _error_page(code, title, message):
    return render_template("errors/error.html", code=code, title=title, message=message), code


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(error):
        if is_api_request():
            return jsonify(ok=False, error=error.to_dict()), error.status_code
        titles = {400: "Bad request", 401: "Login required", 403: "Access denied",
                  404: "Not found", 409: "Action not allowed"}
        return _error_page(error.status_code, titles.get(error.status_code, "Error"), error.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 500:
            message = "Something went wrong on the server. The error has been logged."
        else:
            message = error.description
        if is_api_request():
            return jsonify(ok=False, error={"message": message, "fields": {}}), error.code
        return _error_page(error.code, error.name, message)
