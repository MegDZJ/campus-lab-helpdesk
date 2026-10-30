"""Dashboard statistics, always computed from the database (never hard-coded)."""
from sqlalchemy import func

from ..extensions import db
from ..models import HIGH_PRIORITIES, STATUS_RESOLVED, STATUSES, Ticket


def _status_counts(student_id=None):
    query = db.session.query(Ticket.status, func.count(Ticket.id))
    if student_id is not None:
        query = query.filter(Ticket.student_id == student_id)
    counts = dict(query.group_by(Ticket.status).all())
    stats = {status: counts.get(status, 0) for status in STATUSES}
    stats["total"] = sum(stats.values())
    stats["active"] = stats["total"] - stats[STATUS_RESOLVED]
    return stats


def student_stats(student_id):
    """Counts of one student's own tickets."""
    return _status_counts(student_id)


def lab_stats():
    """Counts across every ticket in the lab (assistants only)."""
    stats = _status_counts()
    unresolved = Ticket.status != STATUS_RESOLVED
    stats["high_priority_unresolved"] = Ticket.query.filter(
        unresolved, Ticket.priority.in_(HIGH_PRIORITIES)
    ).count()
    stats["unassigned"] = Ticket.query.filter(unresolved, Ticket.assignee_id.is_(None)).count()
    return stats


def stats_for(user):
    return lab_stats() if user.is_assistant else student_stats(user.id)
