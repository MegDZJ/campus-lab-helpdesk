"""Database models (SQLite tables) and the fixed choices used across the app."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import column_property
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

# --- Fixed choices -----------------------------------------------------------
# Keys are stored in the database; values are the labels shown to users.

ROLE_STUDENT = "student"
ROLE_ASSISTANT = "assistant"
ROLES = {ROLE_STUDENT: "Student", ROLE_ASSISTANT: "Lab Assistant"}

CATEGORIES = {
    "hardware": "Hardware",
    "software": "Software",
    "network": "Network",
    "login_access": "Login/Access",
    "other": "Other",
}

PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
PRIORITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
HIGH_PRIORITIES = ("high", "critical")

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUSES = {STATUS_OPEN: "Open", STATUS_IN_PROGRESS: "In Progress", STATUS_RESOLVED: "Resolved"}

# Allowed status changes: current status -> statuses it may move to.
STATUS_TRANSITIONS = {
    STATUS_OPEN: (STATUS_IN_PROGRESS,),
    STATUS_IN_PROGRESS: (STATUS_RESOLVED, STATUS_OPEN),
    STATUS_RESOLVED: (STATUS_OPEN,),
}

# Field length limits, enforced by the services and the HTML forms.
TITLE_MIN, TITLE_MAX = 5, 120
DESCRIPTION_MIN, DESCRIPTION_MAX = 10, 2000
WORKSTATION_MAX = 20
MESSAGE_MAX = 1000
ANNOUNCEMENT_TITLE_MIN, ANNOUNCEMENT_TITLE_MAX = 3, 120
ANNOUNCEMENT_CONTENT_MIN, ANNOUNCEMENT_CONTENT_MAX = 5, 2000


def utcnow():
    """Current UTC time as a naive datetime (SQLite has no time-zone type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def isoformat(value):
    """Serialise a stored UTC datetime as ISO 8601, e.g. 2026-10-21T09:15:00Z."""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def format_ticket_number(ticket_id):
    """Human-readable ticket number derived from the primary key: 7 -> LAB-0007."""
    return f"LAB-{ticket_id:04d}"


def _one_of(table, column, choices):
    allowed = ", ".join(f"'{choice}'" for choice in choices)
    return db.CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{table}_{column}")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    __table_args__ = (_one_of("users", "role", ROLES),)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_student(self):
        return self.role == ROLE_STUDENT

    @property
    def is_assistant(self):
        return self.role == ROLE_ASSISTANT

    def to_public_dict(self):
        """Data that is safe to send to any logged-in browser (never the hash)."""
        return {
            "id": self.id,
            "name": self.display_name,
            "username": self.username,
            "role": self.role,
            "role_label": ROLES[self.role],
        }

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    # Set from the primary key right after the INSERT, inside the same
    # transaction, so a committed ticket always has a number.
    ticket_number = db.Column(db.String(20), unique=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    title = db.Column(db.String(TITLE_MAX), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_OPEN, index=True)
    workstation = db.Column(db.String(WORKSTATION_MAX))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    resolved_at = db.Column(db.DateTime)

    # lazy="joined" loads the student and assistant in the same query as the ticket.
    student = db.relationship("User", foreign_keys=[student_id], lazy="joined")
    assignee = db.relationship("User", foreign_keys=[assignee_id], lazy="joined")
    messages = db.relationship(
        "TicketMessage", back_populates="ticket", order_by="TicketMessage.id",
        cascade="all, delete-orphan",
    )
    history = db.relationship(
        "TicketHistory", back_populates="ticket", order_by="TicketHistory.id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        _one_of("tickets", "category", CATEGORIES),
        _one_of("tickets", "priority", PRIORITIES),
        _one_of("tickets", "status", STATUSES),
    )

    def to_dict(self, include_details=False):
        data = {
            "id": self.id,
            "ticket_number": self.ticket_number,
            "title": self.title,
            "category": self.category,
            "category_label": CATEGORIES[self.category],
            "priority": self.priority,
            "priority_label": PRIORITIES[self.priority],
            "status": self.status,
            "status_label": STATUSES[self.status],
            "workstation": self.workstation,
            "student": self.student.to_public_dict(),
            "assignee": self.assignee.to_public_dict() if self.assignee else None,
            "message_count": self.message_count or 0,
            "created_at": isoformat(self.created_at),
            "updated_at": isoformat(self.updated_at),
            "resolved_at": isoformat(self.resolved_at),
            "allowed_transitions": list(STATUS_TRANSITIONS[self.status]),
        }
        if include_details:
            data["description"] = self.description
            data["messages"] = [message.to_dict() for message in self.messages]
            data["history"] = [entry.to_dict() for entry in self.history]
        return data

    def __repr__(self):
        return f"<Ticket {self.ticket_number} {self.status}>"


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="messages")
    sender = db.relationship("User", lazy="joined")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "sender": self.sender.to_public_dict(),
            "body": self.body,
            "created_at": isoformat(self.created_at),
        }


class TicketHistory(db.Model):
    """One row per lifecycle event of a ticket: created, assigned, status changed."""

    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    action = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    ticket = db.relationship("Ticket", back_populates="history")
    actor = db.relationship("User", lazy="joined")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "ticket_number": self.ticket.ticket_number,
            "ticket_title": self.ticket.title,
            "actor": self.actor.to_public_dict(),
            "from_status": self.from_status,
            "to_status": self.to_status,
            "action": self.action,
            "created_at": isoformat(self.created_at),
        }


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(ANNOUNCEMENT_TITLE_MAX), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime)  # set only when the announcement is edited

    author = db.relationship("User", lazy="joined")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "author": self.author.to_public_dict(),
            "created_at": isoformat(self.created_at),
            "updated_at": isoformat(self.updated_at),
        }


# Number of messages per ticket, loaded with the ticket as a correlated subquery
# (avoids one extra query per row in the ticket tables).
Ticket.message_count = column_property(
    select(func.count(TicketMessage.id))
    .where(TicketMessage.ticket_id == Ticket.id)
    .correlate_except(TicketMessage)
    .scalar_subquery()
)
