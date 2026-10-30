"""Server -> client real-time broadcasts over Socket.IO.

Services call these functions only after the change has been committed to
SQLite, so a client never hears about data that is not saved.

Rooms (groups of connected sockets):
    lab               every logged-in connection (announcements)
    role:assistant    every lab assistant connection
    user:<id>         every connection of one user (several tabs or devices)
    ticket:<id>       connections viewing one ticket; joined only after an
                      authorisation check in sockets.py

Every payload carries a unique ``event_id`` so the browser can ignore an event
it has already processed.
"""
import logging
import uuid

from .extensions import socketio
from .models import isoformat, utcnow
from .presence import presence
from .services import stats

log = logging.getLogger("helpdesk")

ROOM_LAB = "lab"
ROOM_ASSISTANTS = "role:assistant"


def user_room(user_id):
    return f"user:{user_id}"


def ticket_room(ticket_id):
    return f"ticket:{ticket_id}"


def _emit(event, payload, rooms):
    """Send one event to the union of ``rooms``; each socket gets it once."""
    socketio.emit(event, {"event_id": uuid.uuid4().hex, **payload}, to=rooms)
    log.debug("emit %s -> %s", event, rooms)


def _notify(rooms, kind, text, actor, ticket=None):
    """Short message that the browser shows as a pop-up notification."""
    _emit("notification", {
        "kind": kind,
        "text": text,
        "actor_id": actor.id if actor else None,
        "ticket_id": ticket.id if ticket else None,
        "ticket_number": ticket.ticket_number if ticket else None,
        "created_at": isoformat(utcnow()),
    }, rooms)


def _ticket_audience(ticket):
    """Everyone allowed to see a ticket: its student and all assistants."""
    return [user_room(ticket.student_id), ROOM_ASSISTANTS]


def stats_changed(student_id):
    _emit("stats:updated", {"scope": "lab", "stats": stats.lab_stats()}, [ROOM_ASSISTANTS])
    _emit("stats:updated", {"scope": "student", "stats": stats.student_stats(student_id)},
          [user_room(student_id)])


def ticket_created(ticket):
    _emit("ticket:created", {"ticket": ticket.to_dict()}, _ticket_audience(ticket))
    _notify([ROOM_ASSISTANTS], "ticket_created",
            f"New {ticket.priority} priority ticket {ticket.ticket_number} from "
            f"{ticket.student.display_name}: {ticket.title}",
            ticket.student, ticket)
    stats_changed(ticket.student_id)


def ticket_updated(ticket, history_entry, change):
    """``change`` is "assigned" or "status"."""
    _emit("ticket:updated", {
        "ticket": ticket.to_dict(),
        "history": history_entry.to_dict(),
        "change": change,
    }, [ticket_room(ticket.id), *_ticket_audience(ticket)])
    _notify(_ticket_audience(ticket), f"ticket_{change}",
            f"{ticket.ticket_number}: {history_entry.action}", history_entry.actor, ticket)
    stats_changed(ticket.student_id)


def ticket_message(ticket, message, client_id=None):
    # The full message goes only to sockets that joined this ticket's room.
    _emit("ticket:message", {
        "ticket_id": ticket.id,
        "message": message.to_dict(),
        "client_id": client_id,
    }, [ticket_room(ticket.id)])
    preview = message.body if len(message.body) <= 80 else message.body[:77] + "..."
    _notify(_ticket_audience(ticket), "ticket_message",
            f"{message.sender.display_name} on {ticket.ticket_number}: {preview}",
            message.sender, ticket)


def announcement_created(announcement):
    _emit("announcement:created", {"announcement": announcement.to_dict()}, [ROOM_LAB])
    _notify([ROOM_LAB], "announcement", f"New announcement: {announcement.title}",
            announcement.author)


def announcement_updated(announcement):
    _emit("announcement:updated", {"announcement": announcement.to_dict()}, [ROOM_LAB])


def announcement_deleted(announcement_id):
    _emit("announcement:deleted", {"announcement_id": announcement_id}, [ROOM_LAB])


def connected_clients():
    """Presence list with each connection's current transport."""
    clients = []
    for info in presence.snapshot():
        try:
            info["transport"] = socketio.server.transport(info["sid"])
        except KeyError:
            info["transport"] = "unknown"  # e.g. disconnected a moment ago
        info["sid"] = info["sid"][:8]  # shortened: enough to tell tabs apart
        info.pop("login_id", None)
        clients.append(info)
    clients.sort(key=lambda client: client["connected_at"])
    return clients


def presence_changed():
    clients = connected_clients()
    _emit("presence:updated", {"clients": clients, "count": len(clients)}, [ROOM_ASSISTANTS])
