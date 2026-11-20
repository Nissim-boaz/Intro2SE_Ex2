import json
import sqlite3

import pytest

from moodleplus.db import connect
from moodleplus.errors import ValidationError
from moodleplus.services.chat import ChatService
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.polls import PollService
from moodleplus.services.users import UserService
from tests.conftest import login


@pytest.fixture
def polls(db):
    return PollService(db)


def _poll_id(db, message_id):
    return db.execute("SELECT poll_id FROM messages WHERE id = ?", (message_id,)).fetchone()[0]


def test_create_poll_posts_chat_message(db, polls, people):
    mid = polls.create(people["course"].id, people["lecturer"], "איזה נושא לחזור?", ["UML", "Design Patterns", ""])
    view = ChatService(db, poll_reader=polls).list_messages(people["course"].id, people["s1"])[0]
    assert view["id"] == mid
    assert view["poll"]["question"] == "איזה נושא לחזור?"
    assert [o["text"] for o in view["poll"]["options"]] == ["UML", "Design Patterns"]  # שורה ריקה נזרקת


def test_poll_validation(polls, people):
    c, lect = people["course"].id, people["lecturer"]
    with pytest.raises(ValidationError):
        polls.create(c, lect, "", ["א", "ב"])
    with pytest.raises(ValidationError):
        polls.create(c, lect, "שאלה", ["רק אחת"])
    with pytest.raises(ValidationError):
        polls.create(c, lect, "שאלה", [str(i) for i in range(7)])
    with pytest.raises(ValidationError):
        polls.create(c, lect, "שאלה", ["א", "א"])


def test_one_vote_per_student_and_change(db, polls, people):
    pid = _poll_id(db, polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"]))
    a, b = [o["id"] for o in polls.results(pid, people["s1"])["options"]]
    polls.vote(pid, people["s1"], a)
    polls.vote(pid, people["s1"], a)
    assert polls.results(pid, people["s1"])["total"] == 1
    polls.vote(pid, people["s1"], b)  # שינוי הצבעה
    res = polls.results(pid, people["s1"])
    assert res["total"] == 1 and res["my_vote"] == b
    assert [o["votes"] for o in res["options"]] == [0, 1]
    polls.vote(pid, people["s2"], b)
    assert [o["votes"] for o in polls.results(pid, people["s2"])["options"]] == [0, 2]


def test_db_enforces_unique_vote(db, polls, people):
    pid = _poll_id(db, polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"]))
    a, b = [o["id"] for o in polls.results(pid, people["s1"])["options"]]
    db.execute("INSERT INTO poll_votes VALUES (?, ?, ?)", (pid, people["s1"].id, a))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO poll_votes VALUES (?, ?, ?)", (pid, people["s1"].id, b))


def test_vote_for_option_of_other_poll_rejected(db, polls, people):
    c, lect = people["course"].id, people["lecturer"]
    p1 = _poll_id(db, polls.create(c, lect, "1", ["א", "ב"]))
    p2 = _poll_id(db, polls.create(c, lect, "2", ["ג", "ד"]))
    foreign = polls.results(p2, people["s1"])["options"][0]["id"]
    with pytest.raises(ValidationError):
        polls.vote(p1, people["s1"], foreign)


def test_results_are_anonymous_for_everyone(db, polls, people):
    pid = _poll_id(db, polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"]))
    polls.vote(pid, people["s1"], polls.results(pid, people["s1"])["options"][0]["id"])
    for viewer in (people["s2"], people["lecturer"], people["admin"]):
        dump = json.dumps(polls.results(pid, viewer), ensure_ascii=False)
        assert "סטודנט אחד" not in dump and str(people["s1"].email) not in dump
        assert "user" not in dump


def test_vote_bumps_message_for_polling(db, polls, people):
    mid = polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"])
    db.execute("UPDATE messages SET updated_at = 1 WHERE id = ?", (mid,))
    db.commit()
    pid = _poll_id(db, mid)
    polls.vote(pid, people["s1"], polls.results(pid, people["s1"])["options"][0]["id"])
    assert db.execute("SELECT updated_at FROM messages WHERE id = ?", (mid,)).fetchone()[0] > 1


# ---------- permissions ----------
def _setup(app):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    lect = users.create("l@test.ac.il", "מרצה", "lecturer")
    stud = users.create("s@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [lect, stud])
    conn.close()
    return lect, stud, course


def test_only_lecturer_creates_polls(app, client):
    lect, stud, course = _setup(app)
    login(client, stud.id)
    assert client.post(f"/api/courses/{course.id}/polls", json={"question": "ש", "options": ["א", "ב"]}).status_code == 403
    login(client, lect.id)
    assert client.post(f"/api/courses/{course.id}/polls", json={"question": "ש", "options": ["א", "ב"]}).status_code == 200


def test_only_students_vote(app, client):
    lect, stud, course = _setup(app)
    login(client, lect.id)
    client.post(f"/api/courses/{course.id}/polls", json={"question": "ש", "options": ["א", "ב"]})
    assert client.post("/api/polls/1/vote", json={"option_id": 1}).status_code == 403
    login(client, stud.id)
    res = client.post("/api/polls/1/vote", json={"option_id": 1})
    assert res.status_code == 200 and res.get_json()["poll"]["total"] == 1


def test_open_poll_shows_who_voted(db, polls, people):
    pid = _poll_id(db, polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"], anonymous=False))
    a, b = [o["id"] for o in polls.results(pid, people["s1"])["options"]]
    polls.vote(pid, people["s1"], a)
    polls.vote(pid, people["s2"], b)
    res = polls.results(pid, people["s2"])
    assert res["anonymous"] is False
    assert [o["voters"] for o in res["options"]] == [["סטודנט אחד"], ["סטודנט שתיים"]]


def test_polls_are_anonymous_by_default(db, polls, people):
    pid = _poll_id(db, polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"]))
    polls.vote(pid, people["s1"], polls.results(pid, people["s1"])["options"][0]["id"])
    res = polls.results(pid, people["lecturer"])
    assert res["anonymous"] is True
    assert all("voters" not in o for o in res["options"])


def test_api_creates_open_poll_only_when_asked(app, client):
    lect, stud, course = _setup(app)
    login(client, lect.id)
    client.post(f"/api/courses/{course.id}/polls", json={"question": "1", "options": ["א", "ב"]})
    client.post(f"/api/courses/{course.id}/polls", json={"question": "2", "options": ["א", "ב"], "anonymous": False})
    conn = connect(app.config["DATABASE"])
    assert [r[0] for r in conn.execute("SELECT anonymous FROM polls ORDER BY id")] == [1, 0]
