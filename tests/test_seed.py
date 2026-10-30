"""The demo seed script must be repeatable without creating duplicates."""
import pytest

import seed_demo
from app import create_app
from app.extensions import db
from app.models import Announcement, Ticket, TicketHistory, TicketMessage, User


@pytest.fixture
def empty_app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'seed.db').as_posix()}",
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def counts(app):
    with app.app_context():
        return tuple(model.query.count() for model in (User, Ticket, TicketMessage, TicketHistory, Announcement))


def test_seed_is_idempotent(empty_app):
    first = seed_demo.seed(empty_app)
    assert first == {"users": 5, "tickets": len(seed_demo.DEMO_TICKETS), "announcements": 3}
    after_first = counts(empty_app)

    second = seed_demo.seed(empty_app)
    assert second == {"users": 0, "tickets": 0, "announcements": 0}
    assert counts(empty_app) == after_first


def test_seed_covers_every_status_and_logs_in(empty_app):
    seed_demo.seed(empty_app)
    with empty_app.app_context():
        statuses = {t.status for t in Ticket.query.all()}
        assert statuses == {"open", "in_progress", "resolved"}
        assert User.query.filter_by(role="student").count() >= 3
        assert User.query.filter_by(username="ravi").first().check_password(seed_demo.ASSISTANT_PASSWORD)
