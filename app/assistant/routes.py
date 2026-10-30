"""Lab assistant pages.

Each page is rendered by Jinja with its initial data embedded as JSON
(``page_data``); static/js/assistant.js and ticket.js draw the lists from that
data and keep them up to date with Socket.IO events.
"""
from flask import current_app, g, render_template

from ..auth.decorators import enforce_role
from ..models import ROLE_ASSISTANT, STATUS_RESOLVED
from ..realtime import connected_clients
from ..services import announcements, network, stats, tickets
from . import bp


def _dicts(items):
    return [item.to_dict() for item in items]


def unassigned_queue(user, limit=6):
    """Unresolved tickets nobody has picked up yet, most urgent first."""
    unassigned = tickets.list_tickets(user, assigned="unassigned", sort="priority")
    return [ticket for ticket in unassigned if ticket.status != STATUS_RESOLVED][:limit]


@bp.before_request
def require_assistant():
    # Runs before every route in this blueprint: lab assistants only.
    return enforce_role(ROLE_ASSISTANT)


@bp.route("/")
def dashboard():
    clients = connected_clients()
    return render_template(
        "assistant_dashboard.html",
        stats=stats.lab_stats(),
        online_count=len(clients),
        page_data={
            "queue": _dicts(unassigned_queue(g.user)),
            "activity": _dicts(tickets.recent_activity(g.user, limit=10)),
        },
    )


@bp.route("/tickets")
def manage_tickets():
    return render_template("assistant_tickets.html",
                           page_data={"tickets": _dicts(tickets.list_tickets(g.user))})


@bp.route("/tickets/<int:ticket_id>")
def ticket_detail(ticket_id):
    ticket = tickets.get_ticket_for_user(g.user, ticket_id)
    return render_template("ticket_detail.html", ticket=ticket,
                           page_data={"ticket": ticket.to_dict(include_details=True)})


@bp.route("/announcements")
def manage_announcements():
    return render_template("assistant_announcements.html",
                           page_data={"announcements": _dicts(announcements.list_announcements())})


@bp.route("/network")
def network_monitor():
    clients = connected_clients()
    info = network.server_info(current_app, len(clients))
    return render_template("assistant_network.html", info=info,
                           page_data={"server": info, "clients": clients})
