"""Create demonstration accounts and realistic sample data.

    python seed_demo.py

Safe to run repeatedly: existing demo users, tickets (matched by student and
title) and announcements (matched by title) are left untouched, so nothing is
duplicated. Data is written directly with the models (not through the
services) so the sample history can have timestamps in the past.
"""
from datetime import timedelta

from dotenv import load_dotenv

from app.extensions import db
from app.models import (
    ROLE_ASSISTANT, ROLE_STUDENT, STATUS_OPEN, STATUS_RESOLVED, Announcement, Ticket,
    TicketHistory, TicketMessage, User, format_ticket_number, utcnow,
)
from app.services.tickets import STATUS_ACTIONS

STUDENT_PASSWORD = "student123"
ASSISTANT_PASSWORD = "assistant123"

DEMO_USERS = [
    ("asha", "Asha Patil", ROLE_STUDENT),
    ("rahul", "Rahul Kulkarni", ROLE_STUDENT),
    ("sneha", "Sneha Desai", ROLE_STUDENT),
    ("ravi", "Ravi Hegde", ROLE_ASSISTANT),
    ("meera", "Meera Joshi", ROLE_ASSISTANT),
]

# Each event: (minutes after the ticket was created, username, kind, value)
DEMO_TICKETS = [
    {
        "student": "asha", "hours_ago": 50, "title": "Monitor shows 'No signal' on PC-12",
        "category": "hardware", "priority": "medium", "workstation": "PC-12",
        "description": "The CPU is switched on and the fans are running, but the monitor "
                       "only shows 'No signal' and then goes to standby.",
        "events": [
            (4, "ravi", "assign", None),
            (5, "ravi", "status", "in_progress"),
            (6, "ravi", "message", "On my way. Is the power light on the monitor amber or green?"),
            (8, "asha", "message", "It's amber, and the computer itself seems to be on."),
            (15, "ravi", "message", "The VGA cable was loose at the back of the CPU. I've "
                                    "reseated it - please check now."),
            (17, "asha", "message", "The display is working now. Thank you!"),
            (18, "ravi", "status", "resolved"),
        ],
    },
    {
        "student": "sneha", "hours_ago": 30, "title": "MySQL Workbench is missing on PC-09",
        "category": "software", "priority": "medium", "workstation": "PC-09",
        "description": "Our DBMS lab exercise needs MySQL Workbench but I cannot find it in "
                       "the applications menu on this computer.",
        "events": [
            (30, "meera", "assign", None),
            (31, "meera", "status", "in_progress"),
            (32, "meera", "message", "It was not part of the last system image. Installing it now."),
            (60, "meera", "status", "resolved"),
            (62, "sneha", "message", "Found it in the menu, thanks!"),
        ],
    },
    {
        "student": "rahul", "hours_ago": 26, "title": "Print jobs stuck in the queue on PC-02",
        "category": "other", "priority": "low", "workstation": "PC-02",
        "description": "My print job has been 'Pending' for 20 minutes and nothing comes out "
                       "of the lab printer.",
        "events": [
            (45, "ravi", "status", "in_progress"),
            (55, "ravi", "message", "I cleared the print spooler; the queue is moving again."),
            (60, "ravi", "status", "resolved"),
        ],
    },
    {
        "student": "rahul", "hours_ago": 5, "title": "Eclipse IDE crashes immediately after launch",
        "category": "software", "priority": "high", "workstation": "PC-07",
        "description": "Eclipse shows the splash screen and then closes with 'An error has "
                       "occurred. See the log file'. My Java lab exercise is due today.",
        "events": [
            (10, "ravi", "assign", None),
            (12, "ravi", "status", "in_progress"),
            (14, "ravi", "message", "Which workspace folder did you select when it started?"),
            (20, "rahul", "message", "The default one in my home folder."),
            (25, "ravi", "message", "The workspace metadata looks corrupted. I'm resetting it - "
                                    "please don't open Eclipse for 5 minutes."),
        ],
    },
    {
        "student": "asha", "hours_ago": 3, "title": "Lab account password expired, cannot log in",
        "category": "login_access", "priority": "medium", "workstation": "PC-03",
        "description": "The login screen says my password has expired, but the change-password "
                       "option gives an 'access denied' error.",
        "events": [
            (20, "meera", "assign", None),
            (21, "meera", "status", "in_progress"),
            (22, "meera", "message", "I've raised a reset request. Please use the guest account "
                                     "until I confirm."),
            (30, "asha", "message", "Okay, I'm using the guest account for now."),
        ],
    },
    {
        "student": "rahul", "hours_ago": 2, "title": "Several keyboard keys not responding",
        "category": "hardware", "priority": "low", "workstation": "PC-15",
        "description": "The E, R and T keys don't type anything. I already tried another USB port.",
        "events": [],
    },
    {
        "student": "asha", "hours_ago": 1, "title": "Projector in Lab 2 not detecting HDMI input",
        "category": "other", "priority": "high", "workstation": "Instructor desk",
        "description": "The projector shows 'No input' even though the laptop is connected "
                       "over HDMI. Our seminar presentation starts at 3 PM.",
        "events": [],
    },
    {
        "student": "sneha", "hours_ago": 0.7, "title": "Cannot reach the lab file server from PC-21",
        "category": "network", "priority": "high", "workstation": "PC-21",
        "description": "The shared practicals folder on the lab server shows 'Network path not "
                       "found'. Other computers in my row can open it, and the network icon "
                       "says connected.",
        "events": [],
    },
    {
        "student": "sneha", "hours_ago": 0.4, "title": "Wi-Fi keeps disconnecting in Lab 3",
        "category": "network", "priority": "critical", "workstation": None,
        "description": "Every laptop in Lab 3 loses the Wi-Fi connection every few minutes, so "
                       "nobody can reach the local exam server.",
        "events": [],
    },
]

DEMO_ANNOUNCEMENTS = [
    ("ravi", 72, "Scheduled maintenance: Lab 2 closed Friday 2-4 PM",
     "Lab 2 will be closed this Friday from 2:00 PM to 4:00 PM for network switch "
     "maintenance. Please use Lab 1 or Lab 3 during this time."),
    ("meera", 20, "New software installed on all lab computers",
     "MySQL Workbench 8.0, VS Code and Python 3.12 are now available on every workstation. "
     "Report any missing tool through the helpdesk."),
    ("ravi", 2, "Please log out before leaving your workstation",
     "Several sessions were left open yesterday. Always log out of your lab account and "
     "close the helpdesk tab before you leave."),
]


def _seed_users():
    users, created = {}, 0
    for username, name, role in DEMO_USERS:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, display_name=name, role=role)
            user.set_password(STUDENT_PASSWORD if role == ROLE_STUDENT else ASSISTANT_PASSWORD)
            db.session.add(user)
            created += 1
        users[username] = user
    db.session.flush()
    return users, created


def _apply_event(ticket, users, when, username, kind, value):
    actor = users[username]
    if kind == "message":
        db.session.add(TicketMessage(ticket=ticket, sender=actor, body=value, created_at=when))
        return
    if kind == "assign":
        ticket.assignee = actor
        action, old, new = f"Assigned to {actor.display_name}", None, None
    else:
        old, new = ticket.status, value
        action = STATUS_ACTIONS[(old, new)]
        if ticket.assignee is None:
            ticket.assignee = actor
            action += f" and assigned to {actor.display_name}"
        ticket.status = new
        ticket.resolved_at = when if new == STATUS_RESOLVED else None
    db.session.add(TicketHistory(ticket=ticket, actor=actor, from_status=old, to_status=new,
                                 action=action, created_at=when))


def _seed_tickets(users, now):
    created = 0
    for spec in sorted(DEMO_TICKETS, key=lambda item: -item["hours_ago"]):
        student = users[spec["student"]]
        if Ticket.query.filter_by(student_id=student.id, title=spec["title"]).first():
            continue
        opened = now - timedelta(hours=spec["hours_ago"])
        ticket = Ticket(student=student, title=spec["title"], description=spec["description"],
                        category=spec["category"], priority=spec["priority"],
                        workstation=spec["workstation"], status=STATUS_OPEN,
                        created_at=opened, updated_at=opened)
        db.session.add(ticket)
        db.session.flush()
        ticket.ticket_number = format_ticket_number(ticket.id)
        db.session.add(TicketHistory(ticket=ticket, actor=student, to_status=STATUS_OPEN,
                                     action="Ticket created", created_at=opened))
        last = opened
        for minutes, username, kind, value in spec["events"]:
            last = opened + timedelta(minutes=minutes)
            _apply_event(ticket, users, last, username, kind, value)
        ticket.updated_at = last
        created += 1
    return created


def _seed_announcements(users, now):
    created = 0
    for username, hours_ago, title, content in DEMO_ANNOUNCEMENTS:
        if Announcement.query.filter_by(title=title).first():
            continue
        db.session.add(Announcement(author=users[username], title=title, content=content,
                                    created_at=now - timedelta(hours=hours_ago)))
        created += 1
    return created


def seed(app):
    """Insert any missing demo data and return how many rows of each kind were added."""
    with app.app_context():
        now = utcnow()
        users, users_created = _seed_users()
        tickets_created = _seed_tickets(users, now)
        announcements_created = _seed_announcements(users, now)
        db.session.commit()
    return {"users": users_created, "tickets": tickets_created,
            "announcements": announcements_created}


if __name__ == "__main__":
    load_dotenv()
    from app import create_app

    summary = seed(create_app())
    print(f"Demo data ready: {summary['users']} users, {summary['tickets']} tickets and "
          f"{summary['announcements']} announcements added "
          "(0 means it already existed).")
    print("Students:   asha / rahul / sneha     password: " + STUDENT_PASSWORD)
    print("Assistants: ravi / meera             password: " + ASSISTANT_PASSWORD)
