"""Start the Campus Lab Helpdesk server on the local network.

    python run.py

The server listens on HOST:PORT (default 0.0.0.0:5000, i.e. every network
interface), so other computers on the same LAN can open
http://<this computer's LAN IP>:5000 in a browser.
"""
import logging
import socket
import sys

from dotenv import load_dotenv

load_dotenv()  # read settings from .env before the app is created

from app import create_app  # noqa: E402
from app.extensions import socketio  # noqa: E402
from app.services.network import detect_lan_ips  # noqa: E402

app = create_app()


class _HideNoisyRequests(logging.Filter):
    """Keep the console readable: hide Socket.IO polling and static-file requests."""

    def filter(self, record):
        message = record.getMessage()
        return "/socket.io/" not in message and "/static/" not in message


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").addFilter(_HideNoisyRequests())


def port_in_use(host, port):
    """True if some program already accepts TCP connections on this port."""
    target = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.create_connection((target, port), timeout=0.5):
            return True  # the TCP handshake succeeded, so someone is listening
    except OSError:
        return False


def print_banner(host, port):
    line = "=" * 64
    print(line)
    print(" Campus Lab Helpdesk - offline LAN server")
    print(line)
    print(f" Listening on   {host}:{port}  (TCP)")
    print(f" This computer  http://127.0.0.1:{port}")
    if host in ("0.0.0.0", "::"):
        lan_ips = detect_lan_ips()
        if lan_ips:
            for ip in lan_ips:
                print(f" LAN clients    http://{ip}:{port}")
        else:
            print(" LAN clients    (no LAN address detected - check your network cable/Wi-Fi)")
        print(" Find the LAN IP manually with:  hostname -I")
    else:
        print(f" Only reachable at {host} - set HOST=0.0.0.0 to accept LAN clients")
    if not app.config.get("SECRET_KEY_FROM_ENV"):
        print(" Note: SECRET_KEY not set - using a generated key stored in")
        print("       instance/.secret_key (fine for a demo, set SECRET_KEY otherwise).")
    print(" Press CTRL+C to stop the server.")
    print(line, flush=True)


if __name__ == "__main__":
    configure_logging()
    host, port = app.config["HOST"], app.config["PORT"]
    if port_in_use(host, port):
        print(f"Port {port} is already in use (is the helpdesk already running?).", file=sys.stderr)
        print(f"Stop the other program or choose another port, e.g.:  PORT={port + 50} python run.py",
              file=sys.stderr)
        sys.exit(1)
    print_banner(host, port)
    try:
        # Werkzeug's development server, multi-threaded, with WebSocket support.
        # allow_unsafe_werkzeug acknowledges this is a demo/LAN deployment.
        socketio.run(app, host=host, port=port, debug=False, use_reloader=False,
                     allow_unsafe_werkzeug=True)
    except OSError as error:
        print(f"Could not start the server on {host}:{port}: {error}", file=sys.stderr)
        print("Is another program using the port? Try:  PORT=5050 python run.py",
              file=sys.stderr)
        sys.exit(1)
