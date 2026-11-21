import pytest

from moodleplus.db import connect
from moodleplus.errors import Forbidden, NotFound, ValidationError
from moodleplus.services.requests import RequestService
from moodleplus.services.users import UserService
from tests.conftest import login


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def reqs(db, clock):
    return RequestService(db, clock=clock)


def test_open_and_validate(reqs, people):
    with pytest.raises(ValidationError):
        reqs.create(people["s1"], " ", "body")
    with pytest.raises(ValidationError):
        reqs.create(people["s1"], "נושא", "  ")
    with pytest.raises(ValidationError):
        reqs.create(people["admin"], "נושא", "admins don't open requests")
    r = reqs.create(people["lecturer"], "לא רואה קורס", "שלום, חסר לי קורס")
    assert r.status == "new" and r.status_label == "חדשה"
    assert [e.body for e in reqs.thread(r.id, people["lecturer"])] == ["שלום, חסר לי קורס"]


def test_only_owner_and_admins_see_a_request(reqs, people):
    r = reqs.create(people["s1"], "נושא", "גוף")
    assert reqs.get_visible(r.id, people["admin"]).id == r.id
    with pytest.raises(Forbidden):
        reqs.get_visible(r.id, people["s2"])
    with pytest.raises(Forbidden):
        reqs.reply(r.id, people["s2"], "hi")
    assert reqs.mine(people["s2"]) == []


def test_admin_reply_moves_to_in_progress_and_flags_the_requester(reqs, people):
    s1, admin = people["s1"], people["admin"]
    r = reqs.create(s1, "נושא", "גוף")
    assert reqs.badge_for(admin) == 1 and reqs.badge_for(s1) == 0
    reqs.reply(r.id, admin, "בודקים")
    r = reqs.get(r.id)
    assert r.status == "in_progress" and r.requester_unseen
    assert reqs.badge_for(admin) == 0 and reqs.badge_for(s1) == 1
    reqs.mark_seen(r.id, s1)
    assert reqs.badge_for(s1) == 0
    kinds = [(e.status, e.body) for e in reqs.thread(r.id, s1)]
    assert kinds == [("", "גוף"), ("in_progress", ""), ("", "בודקים")]


def test_status_changes_and_closed_requests_take_no_replies(reqs, people):
    s1, admin = people["s1"], people["admin"]
    r = reqs.create(s1, "נושא", "גוף")
    with pytest.raises(Forbidden):
        reqs.set_status(r.id, s1, "resolved")
    with pytest.raises(ValidationError):
        reqs.set_status(r.id, admin, "done")
    closed = reqs.set_status(r.id, admin, "rejected")
    assert closed.closed and closed.closed_at > 0
    with pytest.raises(ValidationError):
        reqs.reply(r.id, s1, "עוד משהו")
    reopened = reqs.set_status(r.id, admin, "in_progress")  # reopening clears the deletion clock
    assert not reopened.closed and reopened.closed_at == 0
    reqs.reply(r.id, s1, "תודה")


def test_closed_requests_disappear_after_7_days(reqs, people, clock):
    s1, admin = people["s1"], people["admin"]
    done = reqs.create(s1, "טופלה", "גוף")
    still_open = reqs.create(s1, "פתוחה", "גוף")
    reqs.set_status(done.id, admin, "resolved")
    clock.t += 6 * 86400
    assert {r.id for r in reqs.mine(s1)} == {done.id, still_open.id}
    clock.t += 1 * 86400 + 60
    assert [r.id for r in reqs.mine(s1)] == [still_open.id]
    assert [r.id for r in reqs.all()] == [still_open.id]
    with pytest.raises(NotFound):
        reqs.get(done.id)


def test_inbox_order_and_filter(reqs, people):
    s1, admin = people["s1"], people["admin"]
    a = reqs.create(s1, "א", "גוף")
    b = reqs.create(s1, "ב", "גוף")
    reqs.set_status(a.id, admin, "resolved")
    reqs.set_status(b.id, admin, "in_progress")
    c = reqs.create(s1, "ג", "גוף")
    assert [r.id for r in reqs.all()] == [c.id, b.id, a.id]  # new, in progress, closed
    assert [r.id for r in reqs.all("open")] == [c.id, b.id]
    assert [r.id for r in reqs.all("resolved")] == [a.id]


def test_routes(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    admin = users.find_by_email("admin@test.ac.il")
    stud = users.create("s@test.ac.il", "סטודנטית", "student")
    other = users.create("o@test.ac.il", "סטודנט אחר", "student")
    conn.close()

    login(client, stud.id)
    client.post("/requests", data={"subject": "בעיה בנוכחות", "body": "סומנתי חסרה"})
    assert "בעיה בנוכחות" in client.get("/requests").get_data(as_text=True)
    assert client.post("/requests/1/status", data={"status": "resolved"}).status_code == 403

    login(client, other.id)
    assert "בעיה בנוכחות" not in client.get("/requests").get_data(as_text=True)
    assert client.get("/requests/1").status_code == 302  # Forbidden -> flashed and redirected

    login(client, admin.id)
    inbox = client.get("/admin/requests").get_data(as_text=True)
    assert "בעיה בנוכחות" in inbox and "סטודנטית" in inbox
    client.post("/requests/1/reply", data={"body": "תיקנתי"})
    client.post("/requests/1/status", data={"status": "resolved"})

    login(client, stud.id)
    assert "יש תשובה חדשה" in client.get("/").get_data(as_text=True)  # the dot on the account menu
    page = client.get("/requests/1").get_data(as_text=True)
    assert "תיקנתי" in page and "טופלה" in page and "תימחק בעוד 7 ימים" in page
    assert "יש תשובה חדשה" not in client.get("/").get_data(as_text=True)


def test_admin_can_reply_without_a_name(reqs, people, db):
    s1 = people["s1"]
    users = UserService(db)
    other_admin = users.create("admin2@test.ac.il", "מנהלת שנייה", "admin")
    admin = users.update(people["admin"].id, "נועם המנהל", "admin")
    r = reqs.create(s1, "נושא", "גוף")
    reqs.reply(r.id, admin, "תשובה בלי שם", as_team=True)
    reqs.reply(r.id, admin, "תשובה עם שם")
    reqs.reply(r.id, s1, "student cannot hide", as_team=True)  # ignored for non-admins

    seen_by_student = [e for e in reqs.thread(r.id, s1) if e.body.startswith("תשובה")]
    assert [e.author_name for e in seen_by_student] == ["מנהל המערכת", "נועם המנהל"]
    seen_by_admin = [e for e in reqs.thread(r.id, other_admin) if e.body.startswith("תשובה")]
    assert [(e.author_name, e.as_team) for e in seen_by_admin] == [("נועם המנהל", True), ("נועם המנהל", False)]
    assert not [e for e in reqs.thread(r.id, s1) if e.body == "student cannot hide"][0].as_team


def test_hidden_admin_name_never_reaches_the_requester_page(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    admin = users.update(users.find_by_email("admin@test.ac.il").id, "נועם המנהל", "admin")
    stud = users.create("s@test.ac.il", "סטודנטית", "student")
    conn.close()
    login(client, stud.id)
    client.post("/requests", data={"subject": "נושא", "body": "גוף"})
    login(client, admin.id)
    client.post("/requests/1/reply", data={"body": "בטיפול אצלנו", "as_team": "1"})
    client.post("/requests/1/status", data={"status": "resolved"})
    assert "נועם המנהל" in client.get("/requests/1").get_data(as_text=True)
    login(client, stud.id)
    page = client.get("/requests/1").get_data(as_text=True)
    assert "בטיפול אצלנו" in page and "מנהל המערכת" in page
    assert "נועם המנהל" not in page  # not in the text, a tooltip, or anywhere in the HTML
