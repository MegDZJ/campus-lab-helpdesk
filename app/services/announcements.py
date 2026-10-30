"""Lab announcements: everyone can read them, only assistants can manage them."""
import logging

from .. import realtime
from ..errors import NotFound, PermissionDenied, ValidationError
from ..extensions import db
from ..models import (
    ANNOUNCEMENT_CONTENT_MAX, ANNOUNCEMENT_CONTENT_MIN, ANNOUNCEMENT_TITLE_MAX,
    ANNOUNCEMENT_TITLE_MIN, Announcement, utcnow,
)
from .validation import clean_text, parse_id, require_json_object

log = logging.getLogger("helpdesk")


def _require_assistant(user):
    if not user.is_assistant:
        raise PermissionDenied("Only lab assistants can manage announcements.")


def _clean(data):
    data = require_json_object(data)
    errors = {}
    title = clean_text(data, "title", "Title", ANNOUNCEMENT_TITLE_MIN, ANNOUNCEMENT_TITLE_MAX,
                       errors, single_line=True)
    content = clean_text(data, "content", "Content", ANNOUNCEMENT_CONTENT_MIN,
                         ANNOUNCEMENT_CONTENT_MAX, errors)
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)
    return title, content


def _get(announcement_id):
    announcement = db.session.get(Announcement, parse_id(announcement_id, "announcement ID"))
    if announcement is None:
        raise NotFound("Announcement not found.")
    return announcement


def list_announcements(limit=None):
    query = Announcement.query.order_by(Announcement.created_at.desc(), Announcement.id.desc())
    return query.limit(limit).all() if limit else query.all()


def create_announcement(user, data):
    _require_assistant(user)
    title, content = _clean(data)
    announcement = Announcement(author=user, title=title, content=content)
    db.session.add(announcement)
    db.session.commit()
    log.info("announce '%s' published by %s", title, user.username)
    realtime.announcement_created(announcement)
    return announcement


def update_announcement(user, announcement_id, data):
    _require_assistant(user)
    announcement = _get(announcement_id)
    announcement.title, announcement.content = _clean(data)
    announcement.updated_at = utcnow()
    db.session.commit()
    log.info("announce #%s edited by %s", announcement.id, user.username)
    realtime.announcement_updated(announcement)
    return announcement


def delete_announcement(user, announcement_id):
    _require_assistant(user)
    announcement = _get(announcement_id)
    deleted_id = announcement.id
    db.session.delete(announcement)
    db.session.commit()
    log.info("announce #%s deleted by %s", deleted_id, user.username)
    realtime.announcement_deleted(deleted_id)
