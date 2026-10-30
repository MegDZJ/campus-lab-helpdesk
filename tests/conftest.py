"""Shared test fixtures.

Every test gets a brand-new SQLite file in pytest's temporary directory, so the
demo database in instance/ is never touched.
"""
import pytest

from app import create_app
from app.extensions import db, socketio
from app.models import ROLE_ASSISTANT, ROLE_STUDENT, User
from app.presence import presence

PASSWORD = "password123"

USERS = [
    ("alice", "Alice Student", ROLE_STUDENT),
    ("bob", "Bob Student", ROLE_STUDENT),
    ("carol", "Carol Assistant", ROLE_ASSISTANT),
    ("dave", "Dave Assistant", ROLE_ASSISTANT),
]


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    })
    with app.app_context():
        for username, name, role in USERS:
            user = User(username=username, display_name=name, role=role)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
    presence.clear()
    yield app
    presence.clear()
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


class Client:
    """Wraps Flask's test client: logs in like a browser and sends the CSRF token."""

    def __init__(self, app):
        self.app = app
        self.http = app.test_client()
        self.csrf = None

    def _token_from_session(self):
        with self.http.session_transaction() as session:
            return session.get("_csrf_token")

    def login(self, username, password=PASSWORD):
        self.http.get("/login")  # renders the form, which puts a CSRF token in the session
        response = self.http.post("/login", data={
            "username": username, "password": password, "csrf_token": self._token_from_session(),
        })
        self.http.get("/", follow_redirects=True)  # load a page so a fresh token is issued
        self.csrf = self._token_from_session()
        return response

    def get(self, url, **kwargs):
        return self.http.get(url, **kwargs)

    def _send(self, method, url, json=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if self.csrf:
            headers.setdefault("X-CSRF-Token", self.csrf)
        return self.http.open(url, method=method, json=json, headers=headers, **kwargs)

    def post(self, url, json=None, **kwargs):
        return self._send("POST", url, json, **kwargs)

    def patch(self, url, json=None, **kwargs):
        return self._send("PATCH", url, json, **kwargs)

    def put(self, url, json=None, **kwargs):
        return self._send("PUT", url, json, **kwargs)

    def delete(self, url, **kwargs):
        return self._send("DELETE", url, None, **kwargs)

    def socket(self):
        """Socket.IO test client that shares this browser's session cookie."""
        return socketio.test_client(self.app, flask_test_client=self.http)


@pytest.fixture
def make_client(app):
    def factory(username=None):
        client = Client(app)
        if username:
            client.login(username)
        return client
    return factory


@pytest.fixture
def alice(make_client):
    return make_client("alice")


@pytest.fixture
def bob(make_client):
    return make_client("bob")


@pytest.fixture
def carol(make_client):
    return make_client("carol")


@pytest.fixture
def anonymous(make_client):
    return make_client()


VALID_TICKET = {
    "title": "No network on PC-14",
    "description": "The network icon shows a red cross and websites on the lab server do not load.",
    "category": "network",
    "priority": "high",
    "workstation": "PC-14",
}


@pytest.fixture
def ticket_data():
    return dict(VALID_TICKET)


@pytest.fixture
def alice_ticket(alice, ticket_data):
    """A ticket created by alice through the API; returns its JSON."""
    response = alice.post("/api/tickets", json=ticket_data)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]
