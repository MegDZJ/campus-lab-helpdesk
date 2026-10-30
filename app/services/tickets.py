"""Ticket business rules: creation, access control, assignment, status, messages.

Every function receives the acting ``user`` and checks permissions itself, so
the same rules apply whether the request came over HTTP or Socket.IO.
"""
import logging
import re

from sqlalchemy import case, func, or_

from .. import realtime
from ..errors import Conflict, NotFound, PermissionDenied, ValidationError
from ..extensions import db
from ..models import (
    CATEGORIES, DESCRIPTION_MAX, DESCRIPTION_MIN, MESSAGE_MAX, PRIORITIES, PRIORITY_RANK,
    STATUS_IN_PROGRESS, STATUS_OPEN, STATUS_RESOLVED, STATUS_TRANSITIONS, STATUSES,
    TITLE_MAX, TITLE_MIN, WORKSTATION_MAX, Ticket, TicketHistory, TicketMessage, User,
    format_ticket_number, utcnow,
)
from .validation import clean_choice, clean_pattern, clean_text, parse_id, require_json_object

log = logging.getLogger("helpdesk")

WORKSTATION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9 ._-]*"
CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
SORT_OPTIONS = ("newest", "oldest", "priority", "updated")
ASSIGNMENT_FILTERS = ("me", "unassigned", "assigned")
LIST_LIMIT = 500

# History text for each allowed status change.
STATUS_ACTIONS = {
    (STATUS_OPEN, STATUS_IN_PROGRESS): "Work started",
    (STATUS_IN_PROGRESS, STATUS_RESOLVED): "Marked as resolved",
    (STATUS_IN_PROGRESS, STATUS_OPEN): "Returned to the open queue",
    (STATUS_RESOLVED, STATUS_OPEN): "Ticket reopened",
}


def _require_assistant(user, action):
    if not user.is_assistant:
        raise PermissionDenied(f"Only lab assistants can {action}.")


def can_view_ticket(user, ticket):
    return user.is_assistant or ticket.student_id == user.id


def get_ticket_for_user(user, ticket_id):
    """Load a ticket the user may see.

    A student asking for someone else's ticket gets the same "not found"
    answer as for a ticket that does not exist, so guessing IDs reveals nothing.
    """
    ticket = db.session.get(Ticket, parse_id(ticket_id, "ticket ID"))
    if ticket is None or not can_view_ticket(user, ticket):
        raise NotFound("Ticket not found.")
    return ticket


def create_ticket(student, data):
    if not student.is_student:
        raise PermissionDenied("Only students can create tickets.")
    data = require_json_object(data)
    errors = {}
    title = clean_text(data, "title", "Title", TITLE_MIN, TITLE_MAX, errors, single_line=True)
    description = clean_text(data, "description", "Description", DESCRIPTION_MIN,
                             DESCRIPTION_MAX, errors)
    category = clean_choice(data, "category", "Category", CATEGORIES, errors)
    priority = clean_choice(data, "priority", "Priority", PRIORITIES, errors)
    workstation = clean_pattern(
        data, "workstation", "Workstation", WORKSTATION_PATTERN, WORKSTATION_MAX, errors,
        f"Use up to {WORKSTATION_MAX} letters, digits, spaces, dots or dashes (e.g. PC-14).",
    )
    if errors:
        raise ValidationError("Please correct the highlighted fields.", errors)

    ticket = Ticket(student=student, title=title, description=description, category=category,
                    priority=priority, workstation=workstation, status=STATUS_OPEN)
    db.session.add(ticket)
    db.session.flush()  # sends the INSERT so the database assigns ticket.id
    ticket.ticket_number = format_ticket_number(ticket.id)
    db.session.add(TicketHistory(ticket=ticket, actor=student, to_status=STATUS_OPEN,
                                 action="Ticket created"))
    db.session.commit()

    log.info("ticket   %s created by %s (%s, %s)", ticket.ticket_number, student.username,
             category, priority)
    realtime.ticket_created(ticket)
    return ticket


def list_tickets(user, status=None, category=None, priority=None, assigned=None, q=None,
                 sort="newest", limit=LIST_LIMIT):
    """Tickets visible to ``user`` with optional filters. Students see only their own."""
    query = Ticket.query
    if user.is_student:
        query = query.filter(Ticket.student_id == user.id)

    for value, choices, column, label in (
        (status, STATUSES, Ticket.status, "status"),
        (category, CATEGORIES, Ticket.category, "category"),
        (priority, PRIORITIES, Ticket.priority, "priority"),
    ):
        if value:
            if value not in choices:
                raise ValidationError(f"Unknown {label} filter: {value}")
            query = query.filter(column == value)

    if assigned:
        if assigned not in ASSIGNMENT_FILTERS:
            raise ValidationError(f"Unknown assignment filter: {assigned}")
        if assigned == "me":
            query = query.filter(Ticket.assignee_id == user.id)
        elif assigned == "unassigned":
            query = query.filter(Ticket.assignee_id.is_(None))
        else:
            query = query.filter(Ticket.assignee_id.isnot(None))

    if q and q.strip():
        term = q.strip().lower()[:100]
        conditions = [
            func.lower(Ticket.ticket_number).contains(term, autoescape=True),
            func.lower(Ticket.title).contains(term, autoescape=True),
        ]
        if user.is_assistant:
            conditions.append(Ticket.student.has(or_(
                func.lower(User.display_name).contains(term, autoescape=True),
                func.lower(User.username).contains(term, autoescape=True),
            )))
        query = query.filter(or_(*conditions))

    if sort not in SORT_OPTIONS:
        raise ValidationError(f"Unknown sort order: {sort}")
    if sort == "oldest":
        query = query.order_by(Ticket.created_at.asc(), Ticket.id.asc())
    elif sort == "priority":
        rank = case(PRIORITY_RANK, value=Ticket.priority, else_=0)
        query = query.order_by(rank.desc(), Ticket.created_at.asc())
    elif sort == "updated":
        query = query.order_by(Ticket.updated_at.desc(), Ticket.id.desc())
    else:
        query = query.order_by(Ticket.created_at.desc(), Ticket.id.desc())

    return query.limit(limit).all()


def assign_to_self(assistant, ticket_id):
    _require_assistant(assistant, "assign tickets")
    ticket = get_ticket_for_user(assistant, ticket_id)
    if ticket.status == STATUS_RESOLVED:
        raise Conflict("A resolved ticket cannot be assigned. Reopen it first.")
    if ticket.assignee_id == assistant.id:
        raise Conflict("This ticket is already assigned to you.")

    previous = ticket.assignee
    ticket.assignee = assistant
    ticket.updated_at = utcnow()
    if previous is None:
        action = f"Assigned to {assistant.display_name}"
    else:
        action = f"Reassigned from {previous.display_name} to {assistant.display_name}"
    entry = TicketHistory(ticket=ticket, actor=assistant, action=action)
    db.session.add(entry)
    db.session.commit()

    log.info("ticket   %s %s", ticket.ticket_number, action.lower())
    realtime.ticket_updated(ticket, entry, "assigned")
    return ticket


def change_status(assistant, ticket_id, new_status):
    _require_assistant(assistant, "change ticket status")
    if not isinstance(new_status, str) or new_status not in STATUSES:
        raise ValidationError("Choose a valid status.", {"status": "Unknown status."})
    ticket = get_ticket_for_user(assistant, ticket_id)
    old_status = ticket.status
    if new_status == old_status:
        raise Conflict(f"The ticket is already {STATUSES[old_status]}.")
    if new_status not in STATUS_TRANSITIONS[old_status]:
        raise Conflict(
            f"A ticket cannot move from {STATUSES[old_status]} to {STATUSES[new_status]}."
        )

    action = STATUS_ACTIONS[(old_status, new_status)]
    if new_status == STATUS_IN_PROGRESS and ticket.assignee is None:
        ticket.assignee = assistant  # starting work on an unassigned ticket claims it
        action += f" and assigned to {assistant.display_name}"
    ticket.status = new_status
    ticket.updated_at = utcnow()
    if new_status == STATUS_RESOLVED:
        ticket.resolved_at = ticket.updated_at
    elif old_status == STATUS_RESOLVED:
        ticket.resolved_at = None
    entry = TicketHistory(ticket=ticket, actor=assistant, from_status=old_status,
                          to_status=new_status, action=action)
    db.session.add(entry)
    db.session.commit()

    log.info("ticket   %s %s -> %s by %s", ticket.ticket_number, old_status, new_status,
             assistant.username)
    realtime.ticket_updated(ticket, entry, "status")
    return ticket


def add_message(user, ticket_id, body, client_id=None):
    """Store a conversation message, then push it to the ticket's room.

    ``client_id`` is an optional tag chosen by the sending browser; it is
    echoed back so that browser can match the broadcast to its pending bubble.
    """
    ticket = get_ticket_for_user(user, ticket_id)
    errors = {}
    text = clean_text({"body": body}, "body", "Message", 1, MESSAGE_MAX, errors)
    if errors:
        raise ValidationError(errors["body"], errors)
    if not (isinstance(client_id, str) and CLIENT_ID_PATTERN.fullmatch(client_id)):
        client_id = None

    message = TicketMessage(ticket=ticket, sender=user, body=text)
    db.session.add(message)
    ticket.updated_at = utcnow()
    db.session.commit()

    log.info("message  %s from %s (%d chars)", ticket.ticket_number, user.username, len(text))
    realtime.ticket_message(ticket, message, client_id)
    return message


def recent_activity(user, limit=15):
    """Latest lifecycle events across all tickets (assistants only)."""
    _require_assistant(user, "view lab activity")
    return (TicketHistory.query
            .order_by(TicketHistory.created_at.desc(), TicketHistory.id.desc())
            .limit(limit).all())
