"""Small helpers for validating user input on the server.

Each helper records a friendly message in ``errors`` (field name -> message)
instead of raising immediately, so a form can show every problem at once.
"""
import re

from ..errors import ValidationError


def require_json_object(data):
    if not isinstance(data, dict):
        raise ValidationError("The request body must be a JSON object.")
    return data


def clean_text(data, field, label, min_len, max_len, errors, required=True, single_line=False):
    value = data.get(field)
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors[field] = f"{label} must be text."
        return None
    value = value.strip()
    if single_line:
        value = " ".join(value.split())
    if not value:
        if required:
            errors[field] = f"{label} is required."
        return None
    if len(value) < min_len:
        errors[field] = f"{label} must be at least {min_len} characters."
    elif len(value) > max_len:
        errors[field] = f"{label} must be at most {max_len} characters."
    return value


def clean_choice(data, field, label, choices, errors):
    value = data.get(field)
    if not isinstance(value, str) or value not in choices:
        errors[field] = f"Choose a valid {label.lower()}."
        return None
    return value


def clean_pattern(data, field, label, pattern, max_len, errors, hint):
    """Optional single-line value that must match ``pattern`` when given."""
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        errors[field] = f"{label} must be text."
        return None
    value = value.strip()
    if len(value) > max_len or not re.fullmatch(pattern, value):
        errors[field] = hint
        return None
    return value


def parse_id(value, label="ID"):
    """Convert a client-supplied identifier to a positive int or raise."""
    if isinstance(value, bool):
        value = None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"A valid {label} is required.") from None
    if number < 1:
        raise ValidationError(f"A valid {label} is required.")
    return number
