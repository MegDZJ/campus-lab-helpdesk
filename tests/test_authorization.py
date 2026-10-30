"""Students must never reach another student's data, over HTTP or Socket.IO."""
from app.extensions import db
from app.models import Ticket, TicketMessage


def test_student_cannot_view_another_students_ticket(bob, alice_ticket):
    # 404, not 403: a guessed ID gives no hint that the ticket exists.
    assert bob.get(f"/api/tickets/{alice_ticket['id']}").status_code == 404
    assert bob.get(f"/api/tickets/{alice_ticket['id']}/messages").status_code == 404
    assert bob.get(f"/student/tickets/{alice_ticket['id']}").status_code == 404


def test_student_cannot_message_on_another_students_ticket(bob, alice_ticket, app):
    response = bob.post(f"/api/tickets/{alice_ticket['id']}/messages", json={"body": "hello"})
    assert response.status_code == 404
    with app.app_context():
        assert TicketMessage.query.count() == 0


def test_student_cannot_change_another_students_ticket(bob, alice_ticket, app):
    tid = alice_ticket["id"]
    assert bob.patch(f"/api/tickets/{tid}/status", json={"status": "in_progress"}).status_code == 403
    assert bob.post(f"/api/tickets/{tid}/assign").status_code == 403
    with app.app_context():
        ticket = db.session.get(Ticket, tid)
        assert ticket.status == "open" and ticket.assignee_id is None


def test_anonymous_api_access_is_rejected(anonymous, alice_ticket):
    assert anonymous.get("/api/tickets").status_code == 401
    assert anonymous.get(f"/api/tickets/{alice_ticket['id']}").status_code == 401
    assert anonymous.get("/api/announcements").status_code == 401


def test_student_cannot_use_assistant_api(alice):
    assert alice.get("/api/activity").status_code == 403
    assert alice.get("/api/network").status_code == 403


def test_role_cannot_be_chosen_by_the_client(make_client):
    client = make_client()
    client.get("/login")
    with client.http.session_transaction() as session:
        token = session["_csrf_token"]
    client.http.post("/login?role=assistant",
                     data={"username": "alice", "password": "password123", "role": "assistant",
                           "csrf_token": token})
    assert client.get("/assistant/").status_code == 403


def test_tampered_session_cookie_is_ignored(make_client):
    client = make_client()
    client.http.set_cookie("helpdesk_session", "eyJ1c2VyX2lkIjozfQ.forged.signature")
    assert client.get("/assistant/").status_code == 302  # treated as logged out
