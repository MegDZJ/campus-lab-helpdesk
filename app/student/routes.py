"""Student portal pages.

Each page is rendered by Jinja with its initial data embedded as JSON
(``page_data``); static/js/student.js and ticket.js draw the lists from that
data and keep them up to date with Socket.IO events.
"""
from flask import g, render_template

from ..auth.decorators import enforce_role
from ..models import ROLE_STUDENT
from ..services import announcements, stats, tickets
from . import bp


def _dicts(items):
    return [item.to_dict() for item in items]


@bp.before_request
def require_student():
    # Runs before every route in this blueprint: students only.
    return enforce_role(ROLE_STUDENT)


@bp.route("/")
def dashboard():
    return render_template(
        "student_dashboard.html",
        stats=stats.student_stats(g.user.id),
        page_data={
            "tickets": _dicts(tickets.list_tickets(g.user, limit=5)),
            "announcements": _dicts(announcements.list_announcements(limit=3)),
        },
    )


@bp.route("/tickets/new")
def new_ticket():
    return render_template("ticket_new.html")


@bp.route("/tickets")
def my_tickets():
    return render_template("student_tickets.html",
                           page_data={"tickets": _dicts(tickets.list_tickets(g.user))})


@bp.route("/tickets/<int:ticket_id>")
def ticket_detail(ticket_id):
    ticket = tickets.get_ticket_for_user(g.user, ticket_id)  # 404 if not the owner
    return render_template("ticket_detail.html", ticket=ticket,
                           page_data={"ticket": ticket.to_dict(include_details=True)})


@bp.route("/announcements")
def announcements_page():
    return render_template("announcements.html",
                           page_data={"announcements": _dicts(announcements.list_announcements())})
