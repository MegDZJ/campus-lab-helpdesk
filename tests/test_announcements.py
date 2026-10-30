"""Announcements: assistants publish, everyone reads."""
from app.models import Announcement

ANNOUNCEMENT = {"title": "Lab 2 closed on Friday", "content": "Network maintenance from 2 PM to 4 PM."}


def test_assistant_can_publish(carol, app):
    response = carol.post("/api/announcements", json=ANNOUNCEMENT)
    assert response.status_code == 201
    item = response.get_json()["data"]
    assert item["author"]["username"] == "carol"
    with app.app_context():
        assert Announcement.query.count() == 1


def test_student_cannot_publish(alice, app):
    assert alice.post("/api/announcements", json=ANNOUNCEMENT).status_code == 403
    with app.app_context():
        assert Announcement.query.count() == 0


def test_students_can_view_announcements(carol, alice):
    carol.post("/api/announcements", json=ANNOUNCEMENT)
    items = alice.get("/api/announcements").get_json()["data"]
    assert [item["title"] for item in items] == [ANNOUNCEMENT["title"]]
    page = alice.get("/student/announcements")
    assert page.status_code == 200
    assert ANNOUNCEMENT["title"].encode() in page.data  # embedded in the page data


def test_announcement_validation(carol):
    response = carol.post("/api/announcements", json={"title": "", "content": "x"})
    assert response.status_code == 400
    assert set(response.get_json()["error"]["fields"]) == {"title", "content"}


def test_assistant_can_edit_and_delete(carol, make_client):
    item = carol.post("/api/announcements", json=ANNOUNCEMENT).get_json()["data"]
    dave = make_client("dave")
    edited = dave.put(f"/api/announcements/{item['id']}",
                      json={"title": "Lab 2 closed on Saturday", "content": ANNOUNCEMENT["content"]})
    assert edited.status_code == 200
    assert edited.get_json()["data"]["updated_at"] is not None
    assert dave.delete(f"/api/announcements/{item['id']}").status_code == 200
    assert dave.delete(f"/api/announcements/{item['id']}").status_code == 404


def test_student_cannot_edit_or_delete(carol, alice):
    item = carol.post("/api/announcements", json=ANNOUNCEMENT).get_json()["data"]
    assert alice.put(f"/api/announcements/{item['id']}", json=ANNOUNCEMENT).status_code == 403
    assert alice.delete(f"/api/announcements/{item['id']}").status_code == 403


def test_announcement_content_is_escaped_in_pages(carol, alice):
    carol.post("/api/announcements", json={"title": "<script>alert(1)</script>", "content": "Hello <b>there</b>"})
    body = alice.get("/student/announcements").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
