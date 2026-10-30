"""Information about the server's network setup, shown at startup and on the
assistant's Network page."""
import ipaddress
import platform
import socket
from importlib.metadata import version

from ..models import isoformat, utcnow

STARTED_AT = utcnow()

# Addresses used only to ask the OS which local interface would be used to
# reach them. Connecting a UDP socket sends no packets, so this works offline.
_ROUTE_PROBES = ("8.8.8.8", "10.255.255.255", "172.31.255.255", "192.168.255.255")


def _is_lan_address(ip):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (address.version == 4 and address.is_private
            and not address.is_loopback and not address.is_link_local)


def detect_lan_ips():
    """Best-effort list of this computer's private IPv4 addresses.

    The address of the default-route interface comes first. On Ubuntu the
    command ``hostname -I`` lists the same information.
    """
    found = []
    for probe in _ROUTE_PROBES:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.connect((probe, 9))
                found.append(udp.getsockname()[0])
        except OSError:
            continue  # no route to that range (e.g. no gateway configured)
    try:
        found.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    unique = []
    for ip in found:
        if _is_lan_address(ip) and ip not in unique:
            unique.append(ip)
    return unique


def server_info(app, connected_count):
    port = app.config["PORT"]
    lan_ips = detect_lan_ips()
    uptime = int((utcnow() - STARTED_AT).total_seconds())
    return {
        "hostname": socket.gethostname(),
        "bind_host": app.config["HOST"],
        "port": port,
        "local_url": f"http://127.0.0.1:{port}",
        "lan_urls": [f"http://{ip}:{port}" for ip in lan_ips],
        "transport_protocol": "TCP",
        "application_protocols": ["HTTP/1.1", "WebSocket (Socket.IO)"],
        "async_mode": app.extensions["socketio"].server.eio.async_mode,
        "ping_interval": app.config["SOCKETIO_PING_INTERVAL"],
        "ping_timeout": app.config["SOCKETIO_PING_TIMEOUT"],
        "started_at": isoformat(STARTED_AT),
        "uptime_seconds": uptime,
        "connected_clients": connected_count,
        "python_version": platform.python_version(),
        "flask_socketio_version": version("flask-socketio"),
        "database": "SQLite (" + app.config["SQLALCHEMY_DATABASE_URI"].rsplit("/", 1)[-1] + ")",
    }
