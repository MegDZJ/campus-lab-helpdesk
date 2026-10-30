"""Real-time behaviour, using Flask-SocketIO's test client.

The test client runs the real server-side handlers (connect, rooms, events)
without opening network sockets, and records every event it would receive.
"""
from app.extensions import db
from app.models import TicketMessage


def events(socket, name=None):
    received = socket.get_received()
    return [e for e in received if name is None or e["name"] == name]


def payloads(socket, name):
    return [e["args"][0] for e in events(socket, name)]


def test_unauthenticated_socket_is_refused(anonymous):
    socket = anonymous.socket()
    assert not socket.is_connected()


def test_logged_in_user_can_connect(alice):
    socket = alice.socket()
    assert socket.is_connected()
    ack = socket.emit("net:ping", {}, callback=True)
    assert ack["ok"] is True and ack["data"]["server_time"].endswith("Z")


def test_assistant_receives_new_ticket_in_real_time(alice, carol, ticket_data):
    assistant_socket = carol.socket()
    events(assistant_socket)  # discard connection-time events

    created = alice.post("/api/tickets", json=ticket_data).get_json()["data"]

    received = events(assistant_socket)
    names = [e["name"] for e in received]
    assert "ticket:created" in names and "stats:updated" in names and "notification" in names
    ticket_event = next(e["args"][0] for e in received if e["name"] == "ticket:created")
    assert ticket_event["ticket"]["ticket_number"] == created["ticket_number"]
    assert ticket_event["event_id"]  # used by the browser to drop duplicates
    stats = next(e["args"][0] for e in received if e["name"] == "stats:updated")
    assert stats["scope"] == "lab" and stats["stats"]["open"] == 1


def test_other_students_do_not_receive_new_ticket(alice, bob, ticket_data):
    bob_socket = bob.socket()
    events(bob_socket)
    alice.post("/api/tickets", json=ticket_data)
    assert payloads(bob_socket, "ticket:created") == []
    assert payloads(bob_socket, "stats:updated") == []


def test_student_receives_status_change_and_assignment(alice, carol, alice_ticket):
    student_socket = alice.socket()
    events(student_socket)

    carol.post(f"/api/tickets/{alice_ticket['id']}/assign")
    carol.patch(f"/api/tickets/{alice_ticket['id']}/status", json={"status": "in_progress"})

    updates = payloads(student_socket, "ticket:updated")
    assert [u["change"] for u in updates] == ["assigned", "status"]
    assert updates[-1]["ticket"]["status"] == "in_progress"
    assert updates[-1]["history"]["actor"]["username"] == "carol"


def test_student_can_join_own_ticket_room_only(alice, bob, alice_ticket):
    own = alice.socket().emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)
    assert own["ok"] is True

    guess = bob.socket().emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)
    assert guess["ok"] is False
    assert guess["error"]["message"] == "Ticket not found."


def test_guessing_a_ticket_id_does_not_leak_messages(alice, bob, carol, alice_ticket):
    bob_socket = bob.socket()
    bob_socket.emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)  # rejected
    events(bob_socket)

    carol.post(f"/api/tickets/{alice_ticket['id']}/messages", json={"body": "Private reply for Alice"})

    assert payloads(bob_socket, "ticket:message") == []
    assert all("Private reply" not in str(e) for e in events(bob_socket))


def test_message_reaches_ticket_room(alice, carol, alice_ticket):
    assistant_socket = carol.socket()
    assistant_socket.emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)
    events(assistant_socket)

    alice.post(f"/api/tickets/{alice_ticket['id']}/messages", json={"body": "Still broken", "client_id": "c123"})

    messages = payloads(assistant_socket, "ticket:message")
    assert len(messages) == 1
    assert messages[0]["message"]["body"] == "Still broken"
    assert messages[0]["client_id"] == "c123"


def test_send_message_over_socket_is_acknowledged_and_saved(alice, carol, alice_ticket, app):
    assistant_socket = carol.socket()
    assistant_socket.emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)
    events(assistant_socket)

    ack = alice.socket().emit("ticket:send_message",
                              {"ticket_id": alice_ticket["id"], "body": "Sent over WebSocket", "client_id": "abc"},
                              callback=True)
    assert ack["ok"] is True
    message_id = ack["data"]["message"]["id"]

    with app.app_context():  # the ack is only sent after the row is committed
        assert db.session.get(TicketMessage, message_id).body == "Sent over WebSocket"
    broadcast = payloads(assistant_socket, "ticket:message")
    assert broadcast[0]["message"]["id"] == message_id


def test_socket_message_to_another_students_ticket_is_rejected(bob, alice_ticket, app):
    ack = bob.socket().emit("ticket:send_message", {"ticket_id": alice_ticket["id"], "body": "hi"},
                            callback=True)
    assert ack["ok"] is False
    with app.app_context():
        assert TicketMessage.query.count() == 0


def test_malformed_socket_events_are_rejected(alice):
    socket = alice.socket()
    assert socket.emit("ticket:join", "not-an-object", callback=True)["ok"] is False
    assert socket.emit("ticket:join", {"ticket_id": "abc"}, callback=True)["ok"] is False
    assert socket.emit("ticket:join", {}, callback=True)["ok"] is False
    assert socket.emit("ticket:send_message", {"ticket_id": 1}, callback=True)["ok"] is False


def test_announcement_is_broadcast_to_everyone(alice, bob, carol):
    sockets = [alice.socket(), bob.socket()]
    for socket in sockets:
        events(socket)
    carol.post("/api/announcements", json={"title": "Server maintenance", "content": "Back at 3 PM."})
    for socket in sockets:
        created = payloads(socket, "announcement:created")
        assert created and created[0]["announcement"]["title"] == "Server maintenance"


def test_presence_is_tracked_and_shown_to_assistants(alice, carol):
    assistant_socket = carol.socket()
    events(assistant_socket)
    student_socket = alice.socket()

    update = payloads(assistant_socket, "presence:updated")[-1]
    assert {c["username"] for c in update["clients"]} == {"alice", "carol"}
    assert all("login_id" not in c for c in update["clients"])
    assert payloads(student_socket, "presence:updated") == []  # students never see IP addresses

    student_socket.disconnect()
    update = payloads(assistant_socket, "presence:updated")[-1]
    assert {c["username"] for c in update["clients"]} == {"carol"}


def test_logout_disconnects_live_sockets(alice):
    socket = alice.socket()
    assert socket.is_connected()
    alice.post("/logout")
    assert not socket.is_connected()


def test_duplicate_room_membership_delivers_event_once(alice, carol, alice_ticket):
    # The assistant is in both "role:assistant" and "ticket:<id>"; ticket:updated
    # targets both rooms but must arrive only once.
    assistant_socket = carol.socket()
    assistant_socket.emit("ticket:join", {"ticket_id": alice_ticket["id"]}, callback=True)
    events(assistant_socket)
    carol.patch(f"/api/tickets/{alice_ticket['id']}/status", json={"status": "in_progress"})
    assert len(payloads(assistant_socket, "ticket:updated")) == 1
