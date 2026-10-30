"""In-memory registry of the Socket.IO connections that are currently open.

This is connection state, not business data: it is rebuilt automatically as
clients reconnect after a server restart, so it does not belong in SQLite.
Handler threads run concurrently, hence the lock.
"""
import threading

from .models import isoformat, utcnow


class PresenceRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}

    def add(self, sid, user, ip_address, login_id):
        with self._lock:
            self._clients[sid] = {
                "sid": sid,
                "user_id": user.id,
                "name": user.display_name,
                "username": user.username,
                "role": user.role,
                "ip": ip_address,
                "login_id": login_id,
                "connected_at": isoformat(utcnow()),
            }

    def remove(self, sid):
        with self._lock:
            return self._clients.pop(sid, None)

    def get(self, sid):
        with self._lock:
            info = self._clients.get(sid)
            return dict(info) if info else None

    def sids_for_login(self, login_id):
        """Socket ids opened by one browser login session (used at logout)."""
        if not login_id:
            return []
        with self._lock:
            return [sid for sid, info in self._clients.items() if info["login_id"] == login_id]

    def snapshot(self):
        with self._lock:
            return [dict(info) for info in self._clients.values()]

    def clear(self):
        with self._lock:
            self._clients.clear()


presence = PresenceRegistry()
