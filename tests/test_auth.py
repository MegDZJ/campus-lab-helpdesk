"""Login, logout, CSRF and page access by role."""
from app.models import User


def test_login_page_loads(anonymous):
    response = anonymous.get("/login")
    assert response.status_code == 200
    assert b"Log in" in response.data


def test_valid_login_redirects_to_role_dashboard(make_client):
    student = make_client()
    response = student.login("alice")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student/")

    assistant = make_client()
    response = assistant.login("carol")
    assert response.headers["Location"].endswith("/assistant/")


def test_username_is_case_insensitive(make_client):
    client = make_client()
    assert client.login("ALICE").status_code == 302


def test_invalid_password_is_rejected(make_client):
    client = make_client()
    response = client.login("alice", password="wrong-password")
    assert response.status_code == 401
    assert b"Incorrect username or password" in response.data
    assert client.get("/student/").status_code == 302  # still not logged in


def test_unknown_user_is_rejected(make_client):
    response = make_client().login("nobody")
    assert response.status_code == 401


def test_passwords_are_hashed(app):
    with app.app_context():
        user = User.query.filter_by(username="alice").first()
        assert user.password_hash != "password123"
        assert user.check_password("password123")
        assert not user.check_password("password124")


def test_login_without_csrf_token_is_rejected(anonymous):
    anonymous.get("/login")
    response = anonymous.http.post("/login", data={"username": "alice", "password": "password123"})
    assert response.status_code == 400


def test_api_post_without_csrf_header_is_rejected(alice, ticket_data):
    response = alice.http.post("/api/tickets", json=ticket_data)  # no X-CSRF-Token header
    assert response.status_code == 400
    assert "security token" in response.get_json()["error"]["message"]


def test_logout_clears_session(alice):
    assert alice.get("/student/").status_code == 200
    response = alice.post("/logout")
    assert response.status_code == 302
    assert alice.get("/student/").status_code == 302
    assert alice.get("/api/tickets").status_code == 401


def test_logout_requires_post(alice):
    assert alice.get("/logout").status_code == 405


def test_anonymous_user_is_sent_to_login(anonymous):
    response = anonymous.get("/student/tickets")
    assert response.status_code == 302
    assert "/login?next=/student/tickets" in response.headers["Location"]


def test_login_follows_safe_next_only(make_client):
    client = make_client()
    client.get("/login")
    with client.http.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.http.post("/login?next=//evil.example.com",
                                data={"username": "alice", "password": "password123", "csrf_token": token})
    assert response.headers["Location"].endswith("/student/")


def test_student_can_open_student_pages(alice, alice_ticket):
    for url in ["/student/", "/student/tickets", "/student/tickets/new", "/student/announcements",
                f"/student/tickets/{alice_ticket['id']}"]:
        assert alice.get(url).status_code == 200, url


def test_student_is_denied_assistant_pages(alice):
    for url in ["/assistant/", "/assistant/tickets", "/assistant/announcements", "/assistant/network"]:
        assert alice.get(url).status_code == 403, url


def test_assistant_can_open_assistant_pages(carol, alice_ticket):
    for url in ["/assistant/", "/assistant/tickets", "/assistant/announcements", "/assistant/network",
                f"/assistant/tickets/{alice_ticket['id']}"]:
        assert carol.get(url).status_code == 200, url


def test_assistant_is_denied_student_pages(carol):
    assert carol.get("/student/").status_code == 403


def test_api_never_returns_password_hashes(carol, alice_ticket):
    body = carol.get(f"/api/tickets/{alice_ticket['id']}").get_data(as_text=True)
    assert "password" not in body
    assert "scrypt" not in body and "pbkdf2" not in body


def test_health_endpoint_is_public(anonymous):
    response = anonymous.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "up"
