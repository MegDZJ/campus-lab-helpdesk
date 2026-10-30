"""Ticket creation, listing, status workflow, assignment and messages."""
import pytest

from app.extensions import db
from app.models import Ticket, TicketHistory, TicketMessage


def test_create_ticket_with_valid_data(alice, ticket_data, app):
    response = alice.post("/api/tickets", json=ticket_data)
    assert response.status_code == 201
    ticket = response.get_json()["data"]
    assert ticket["ticket_number"] == f"LAB-{ticket['id']:04d}"
    assert ticket["status"] == "open"
    assert ticket["student"]["username"] == "alice"
    assert ticket["assignee"] is None
    assert ticket["created_at"].endswith("Z")  # timestamp set by the server
    assert ticket["history"][0]["action"] == "Ticket created"

    with app.app_context():
        stored = db.session.get(Ticket, ticket["id"])
        assert stored.title == ticket_data["title"]
        assert stored.workstation == "PC-14"


def test_ticket_numbers_are_unique(alice, bob, ticket_data):
    numbers = {alice.post("/api/tickets", json=ticket_data).get_json()["data"]["ticket_number"],
               bob.post("/api/tickets", json=ticket_data).get_json()["data"]["ticket_number"],
               alice.post("/api/tickets", json=ticket_data).get_json()["data"]["ticket_number"]}
    assert len(numbers) == 3


def test_workstation_is_optional(alice, ticket_data):
    ticket_data.pop("workstation")
    response = alice.post("/api/tickets", json=ticket_data)
    assert response.status_code == 201
    assert response.get_json()["data"]["workstation"] is None


@pytest.mark.parametrize("field, value", [
    ("title", ""),
    ("title", "abc"),
    ("title", "x" * 121),
    ("description", "short"),
    ("description", "x" * 2001),
    ("category", "printer"),
    ("priority", "urgent"),
    ("priority", None),
    ("workstation", "PC 14; DROP TABLE"),
    ("title", ["not", "text"]),
])
def test_invalid_ticket_fields_are_rejected(alice, ticket_data, app, field, value):
    ticket_data[field] = value
    response = alice.post("/api/tickets", json=ticket_data)
    assert response.status_code == 400
    assert field in response.get_json()["error"]["fields"]
    with app.app_context():
        assert Ticket.query.count() == 0


def test_missing_body_is_rejected(alice):
    response = alice.post("/api/tickets", data="not json", content_type="text/plain")
    assert response.status_code == 400


def test_assistant_cannot_create_ticket(carol, ticket_data):
    assert carol.post("/api/tickets", json=ticket_data).status_code == 403


def test_student_sees_only_own_tickets(alice, bob, ticket_data):
    alice.post("/api/tickets", json=ticket_data)
    bob.post("/api/tickets", json={**ticket_data, "title": "Bob's broken mouse"})
    alice_list = alice.get("/api/tickets").get_json()["data"]
    assert [t["student"]["username"] for t in alice_list] == ["alice"]


def test_student_can_view_own_ticket(alice, alice_ticket):
    response = alice.get(f"/api/tickets/{alice_ticket['id']}")
    assert response.status_code == 200
    assert response.get_json()["data"]["description"]


def test_assistant_sees_all_tickets(alice, bob, carol, ticket_data):
    alice.post("/api/tickets", json=ticket_data)
    bob.post("/api/tickets", json={**ticket_data, "title": "Bob's broken mouse"})
    tickets = carol.get("/api/tickets").get_json()["data"]
    assert {t["student"]["username"] for t in tickets} == {"alice", "bob"}


def test_assistant_filters_and_search(alice, bob, carol, ticket_data):
    alice.post("/api/tickets", json=ticket_data)
    bob.post("/api/tickets", json={**ticket_data, "title": "Mouse not working", "category": "hardware",
                                   "priority": "low"})
    assert len(carol.get("/api/tickets?category=hardware").get_json()["data"]) == 1
    assert len(carol.get("/api/tickets?priority=high").get_json()["data"]) == 1
    assert len(carol.get("/api/tickets?q=bob").get_json()["data"]) == 1  # by student name
    assert len(carol.get("/api/tickets?q=mouse").get_json()["data"]) == 1  # by title
    assert len(carol.get("/api/tickets?q=LAB-0001").get_json()["data"]) == 1  # by ticket number
    assert len(carol.get("/api/tickets?assigned=unassigned").get_json()["data"]) == 2
    by_priority = carol.get("/api/tickets?sort=priority").get_json()["data"]
    assert [t["priority"] for t in by_priority] == ["high", "low"]


def test_search_treats_wildcards_literally(carol, alice, ticket_data):
    alice.post("/api/tickets", json=ticket_data)
    assert carol.get("/api/tickets?q=%25").get_json()["data"] == []  # '%' is not a wildcard


def test_invalid_filter_is_rejected(carol):
    assert carol.get("/api/tickets?status=closed").status_code == 400
    assert carol.get("/api/tickets?sort=random").status_code == 400


def test_valid_status_transitions(carol, alice_ticket, app):
    url = f"/api/tickets/{alice_ticket['id']}/status"

    started = carol.patch(url, json={"status": "in_progress"}).get_json()["data"]
    assert started["status"] == "in_progress"
    assert started["assignee"]["username"] == "carol"  # starting work claims the ticket

    resolved = carol.patch(url, json={"status": "resolved"}).get_json()["data"]
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None

    reopened = carol.patch(url, json={"status": "open"}).get_json()["data"]
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None

    with app.app_context():
        changes = [(h.from_status, h.to_status) for h in
                   TicketHistory.query.filter(TicketHistory.to_status.isnot(None)).order_by(TicketHistory.id)]
    assert changes == [(None, "open"), ("open", "in_progress"), ("in_progress", "resolved"),
                       ("resolved", "open")]


def test_invalid_status_transitions(carol, alice_ticket):
    url = f"/api/tickets/{alice_ticket['id']}/status"
    skip = carol.patch(url, json={"status": "resolved"})  # open -> resolved is not allowed
    assert skip.status_code == 409
    same = carol.patch(url, json={"status": "open"})
    assert same.status_code == 409
    unknown = carol.patch(url, json={"status": "closed"})
    assert unknown.status_code == 400
    missing = carol.patch(url, json={})
    assert missing.status_code == 400


def test_student_cannot_change_status(alice, alice_ticket):
    response = alice.patch(f"/api/tickets/{alice_ticket['id']}/status", json={"status": "in_progress"})
    assert response.status_code == 403


def test_assign_to_self(carol, alice_ticket):
    url = f"/api/tickets/{alice_ticket['id']}/assign"
    ticket = carol.post(url).get_json()["data"]
    assert ticket["assignee"]["username"] == "carol"
    assert ticket["history"][-1]["action"] == "Assigned to Carol Assistant"
    assert carol.post(url).status_code == 409  # already assigned to carol


def test_another_assistant_can_take_over(carol, make_client, alice_ticket):
    carol.post(f"/api/tickets/{alice_ticket['id']}/assign")
    dave = make_client("dave")
    ticket = dave.post(f"/api/tickets/{alice_ticket['id']}/assign").get_json()["data"]
    assert ticket["assignee"]["username"] == "dave"
    assert "Reassigned from Carol Assistant" in ticket["history"][-1]["action"]


def test_resolved_ticket_cannot_be_assigned(carol, make_client, alice_ticket):
    status_url = f"/api/tickets/{alice_ticket['id']}/status"
    carol.patch(status_url, json={"status": "in_progress"})
    carol.patch(status_url, json={"status": "resolved"})
    dave = make_client("dave")
    assert dave.post(f"/api/tickets/{alice_ticket['id']}/assign").status_code == 409


def test_student_cannot_assign(alice, alice_ticket):
    assert alice.post(f"/api/tickets/{alice_ticket['id']}/assign").status_code == 403


def test_messages_are_persisted(alice, carol, alice_ticket, app):
    url = f"/api/tickets/{alice_ticket['id']}/messages"
    first = alice.post(url, json={"body": "  The cable looks fine.  "})
    assert first.status_code == 201
    assert first.get_json()["data"]["body"] == "The cable looks fine."
    carol.post(url, json={"body": "Coming to PC-14 now."})

    messages = alice.get(url).get_json()["data"]
    assert [m["sender"]["username"] for m in messages] == ["alice", "carol"]
    with app.app_context():
        assert TicketMessage.query.count() == 2
    listed = carol.get("/api/tickets").get_json()["data"][0]
    assert listed["message_count"] == 2


def test_empty_or_long_messages_are_rejected(alice, alice_ticket):
    url = f"/api/tickets/{alice_ticket['id']}/messages"
    assert alice.post(url, json={"body": "   "}).status_code == 400
    assert alice.post(url, json={"body": "x" * 1001}).status_code == 400
    assert alice.post(url, json={}).status_code == 400


def test_missing_ticket_returns_404(carol):
    assert carol.get("/api/tickets/9999").status_code == 404
    assert carol.patch("/api/tickets/9999/status", json={"status": "in_progress"}).status_code == 404
    assert carol.get("/assistant/tickets/9999").status_code == 404


def test_stats_are_computed_from_database(alice, bob, carol, ticket_data):
    alice.post("/api/tickets", json=ticket_data)
    bob_ticket = bob.post("/api/tickets", json={**ticket_data, "priority": "low"}).get_json()["data"]
    carol.patch(f"/api/tickets/{bob_ticket['id']}/status", json={"status": "in_progress"})

    lab = carol.get("/api/stats").get_json()["data"]
    assert lab["total"] == 2 and lab["open"] == 1 and lab["in_progress"] == 1
    assert lab["high_priority_unresolved"] == 1
    assert lab["unassigned"] == 1

    mine = alice.get("/api/stats").get_json()["data"]
    assert mine == {"open": 1, "in_progress": 0, "resolved": 0, "total": 1, "active": 1}
