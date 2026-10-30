"""JSON API used by the browser (fetch) and by the tests.

Success: {"ok": true, "data": ...}
Failure: {"ok": false, "error": {"message": "...", "fields": {...}}}
with status 400 (invalid input), 401 (not logged in), 403 (wrong role),
404 (not found or not yours) or 409 (not allowed in the current state).
"""
from flask import current_app, g, jsonify, request

from ..auth.decorators import login_required, role_required
from ..models import ROLE_ASSISTANT, ROLE_STUDENT, isoformat, utcnow
from ..realtime import connected_clients
from ..services import announcements, network, stats, tickets
from . import bp


def ok(data=None, status=200):
    return jsonify(ok=True, data=data), status


def json_body():
    return request.get_json(silent=True)


@bp.get("/health")
def health():
    """Unauthenticated reachability check, e.g. curl http://SERVER_IP:5000/api/health"""
    return ok({"status": "up", "server_time": isoformat(utcnow())})


@bp.get("/me")
@login_required
def me():
    return ok(g.user.to_public_dict())


@bp.get("/stats")
@login_required
def get_stats():
    return ok(stats.stats_for(g.user))


@bp.get("/tickets")
@login_required
def list_tickets():
    args = request.args
    found = tickets.list_tickets(
        g.user,
        status=args.get("status") or None,
        category=args.get("category") or None,
        priority=args.get("priority") or None,
        assigned=args.get("assigned") or None,
        q=args.get("q") or None,
        sort=args.get("sort") or "newest",
    )
    return ok([ticket.to_dict() for ticket in found])


@bp.post("/tickets")
@role_required(ROLE_STUDENT)
def create_ticket():
    ticket = tickets.create_ticket(g.user, json_body())
    return ok(ticket.to_dict(include_details=True), 201)


@bp.get("/tickets/<int:ticket_id>")
@login_required
def get_ticket(ticket_id):
    ticket = tickets.get_ticket_for_user(g.user, ticket_id)
    return ok(ticket.to_dict(include_details=True))


@bp.get("/tickets/<int:ticket_id>/messages")
@login_required
def get_messages(ticket_id):
    ticket = tickets.get_ticket_for_user(g.user, ticket_id)
    return ok([message.to_dict() for message in ticket.messages])


@bp.post("/tickets/<int:ticket_id>/messages")
@login_required
def post_message(ticket_id):
    data = json_body() or {}
    message = tickets.add_message(g.user, ticket_id, data.get("body"), data.get("client_id"))
    return ok(message.to_dict(), 201)


@bp.post("/tickets/<int:ticket_id>/assign")
@role_required(ROLE_ASSISTANT)
def assign_ticket(ticket_id):
    ticket = tickets.assign_to_self(g.user, ticket_id)
    return ok(ticket.to_dict(include_details=True))


@bp.patch("/tickets/<int:ticket_id>/status")
@role_required(ROLE_ASSISTANT)
def update_status(ticket_id):
    data = json_body() or {}
    ticket = tickets.change_status(g.user, ticket_id, data.get("status"))
    return ok(ticket.to_dict(include_details=True))


@bp.get("/activity")
@role_required(ROLE_ASSISTANT)
def activity():
    return ok([entry.to_dict() for entry in tickets.recent_activity(g.user)])


@bp.get("/announcements")
@login_required
def list_announcements():
    return ok([item.to_dict() for item in announcements.list_announcements()])


@bp.post("/announcements")
@role_required(ROLE_ASSISTANT)
def create_announcement():
    item = announcements.create_announcement(g.user, json_body())
    return ok(item.to_dict(), 201)


@bp.put("/announcements/<int:announcement_id>")
@role_required(ROLE_ASSISTANT)
def update_announcement(announcement_id):
    item = announcements.update_announcement(g.user, announcement_id, json_body())
    return ok(item.to_dict())


@bp.delete("/announcements/<int:announcement_id>")
@role_required(ROLE_ASSISTANT)
def delete_announcement(announcement_id):
    announcements.delete_announcement(g.user, announcement_id)
    return ok({"id": announcement_id})


@bp.get("/network")
@role_required(ROLE_ASSISTANT)
def network_status():
    clients = connected_clients()
    return ok({"server": network.server_info(current_app, len(clients)), "clients": clients})
