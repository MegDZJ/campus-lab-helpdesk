"""Client -> server Socket.IO events and connection lifecycle.

Each browser tab keeps one persistent Socket.IO connection (WebSocket over
TCP, or HTTP long-polling as a fallback). The handshake carries the normal
login cookie, so the connection is authenticated with the same Flask session
as the HTTP pages; anonymous connections are refused.

Events a client may send (each answers through a Socket.IO acknowledgement
callback with {"ok": true, "data": ...} or {"ok": false, "error": {...}}):
    ticket:join          {ticket_id}           subscribe to one ticket's live updates
    ticket:leave         {ticket_id}           unsubscribe
    ticket:send_message  {ticket_id, body, client_id}
    net:ping             {}                    round-trip-time measurement
    client:transport     {}                    "my transport changed" hint
"""
import logging
from functools import wraps

from flask import request, session
from flask_socketio import ConnectionRefusedError, join_room, leave_room

from . import realtime
from .errors import AppError, ValidationError
from .extensions import db, socketio
from .models import User, isoformat, utcnow
from .presence import presence
from .services import tickets
from .services.validation import parse_id

log = logging.getLogger("helpdesk")


def _ok(data=None):
    return {"ok": True, "data": data}


def _error(message):
    return {"ok": False, "error": {"message": message, "fields": {}}}


def _socket_user():
    info = presence.get(request.sid)
    return db.session.get(User, info["user_id"]) if info else None


def authenticated_event(handler):
    """Reject events from unknown sockets and turn AppErrors into error acks."""
    @wraps(handler)
    def wrapped(data=None):
        user = _socket_user()
        if user is None:
            return _error("You are not logged in.")
        if data is not None and not isinstance(data, dict):
            return _error("Event data must be an object.")
        try:
            return handler(user, data or {})
        except AppError as error:
            db.session.rollback()
            return {"ok": False, "error": error.to_dict()}
    return wrapped


@socketio.on("connect")
def on_connect(auth=None):
    user_id = session.get("user_id")
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        log.info("socket   refused unauthenticated connection from %s", request.remote_addr)
        raise ConnectionRefusedError("unauthorized")

    presence.add(request.sid, user, request.remote_addr, session.get("login_id"))
    join_room(realtime.ROOM_LAB)
    join_room(realtime.user_room(user.id))
    if user.is_assistant:
        join_room(realtime.ROOM_ASSISTANTS)
    log.info("socket   connected    %-10s (%s) from %s", user.username, user.role,
             request.remote_addr)
    realtime.presence_changed()


@socketio.on("disconnect")
def on_disconnect(reason=None):
    info = presence.remove(request.sid)
    if info:
        log.info("socket   disconnected %-10s from %s (%s)", info["username"], info["ip"],
                 reason or "closed")
        realtime.presence_changed()


@socketio.on("ticket:join")
@authenticated_event
def on_ticket_join(user, data):
    # Same check as the HTTP API: students may only join their own tickets.
    ticket = tickets.get_ticket_for_user(user, data.get("ticket_id"))
    join_room(realtime.ticket_room(ticket.id))
    return _ok({"ticket_id": ticket.id})


@socketio.on("ticket:leave")
@authenticated_event
def on_ticket_leave(user, data):
    ticket_id = parse_id(data.get("ticket_id"), "ticket ID")
    leave_room(realtime.ticket_room(ticket_id))
    return _ok({"ticket_id": ticket_id})


@socketio.on("ticket:send_message")
@authenticated_event
def on_send_message(user, data):
    if "body" not in data:
        raise ValidationError("Message is required.")
    message = tickets.add_message(user, data.get("ticket_id"), data.get("body"),
                                  data.get("client_id"))
    # The ack is the delivery receipt: the message is now stored in SQLite.
    return _ok({"message": message.to_dict()})


@socketio.on("net:ping")
@authenticated_event
def on_ping(user, data):
    return _ok({"server_time": isoformat(utcnow())})


@socketio.on("client:transport")
@authenticated_event
def on_transport_change(user, data):
    realtime.presence_changed()
    return _ok()


@socketio.on_error_default
def on_socket_error(error):
    log.exception("socket   unhandled error in event handler: %s", error)
    db.session.rollback()
    return _error("Server error while handling the event.")
