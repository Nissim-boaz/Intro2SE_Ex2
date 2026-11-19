import json

import pytest

from modelplus.db import connect
from modelplus.errors import ValidationError
from modelplus.services.chat import ANONYMOUS_NAME, ChatService, ReactionService
from modelplus.services.courses import CourseService, EnrollmentService
from modelplus.services.polls import PollService
from modelplus.services.users import UserService
from tests.conftest import login


@pytest.fixture
def chat(db):
    return ChatService(db, poll_reader=PollService(db))


def _only(messages, mid):
    return next(m for m in messages if m["id"] == mid)


# ---------- messages ----------
def test_send_and_list(chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "שלום 👋")
    view = _only(chat.list_messages(c, people["s2"]), mid)
    assert view["body"] == "שלום 👋" and view["sender_name"] == "סטודנט אחד" and not view["mine"]
    assert _only(chat.list_messages(c, people["s1"]), mid)["mine"]


def test_empty_and_too_long_rejected(chat, people):
    c = people["course"].id
    with pytest.raises(ValidationError):
        chat.send(c, people["s1"], "   ")
    with pytest.raises(ValidationError):
        chat.send(c, people["s1"], "א" * 2001)


def test_reply_shows_quote(chat, people):
    c = people["course"].id
    q = chat.send(c, people["s1"], "מתי המבחן?")
    a = chat.send(c, people["lecturer"], "ב-3 בפברואר", reply_to_id=q)
    view = _only(chat.list_messages(c, people["s2"]), a)
    assert view["reply_to"] == {"id": q, "sender_name": "סטודנט אחד", "body": "מתי המבחן?"}
    assert view["sender_is_lecturer"]


def test_reply_to_other_course_rejected(db, chat, people):
    other = CourseService(db).create("אחר")
    mid = chat.send(other.id, people["admin"], "x")
    with pytest.raises(ValidationError):
        chat.send(people["course"].id, people["s1"], "y", reply_to_id=mid)


def test_since_returns_only_changed(chat, people, db):
    c = people["course"].id
    a = chat.send(c, people["s1"], "ראשונה")
    db.execute("UPDATE messages SET updated_at = 100 WHERE id = ?", (a,))
    b = chat.send(c, people["s1"], "שנייה")
    ids = [m["id"] for m in chat.list_messages(c, people["s2"], since=200)]
    assert ids == [b]


# ---------- anonymity ----------
def test_anonymous_hidden_from_student_and_lecturer(chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "שאלה מביכה", anonymous=True)
    for viewer in (people["s2"], people["lecturer"]):
        view = _only(chat.list_messages(c, viewer), mid)
        assert view["sender_name"] == ANONYMOUS_NAME
        assert "sender_id" not in view
        assert not view["sender_is_lecturer"]
        # שום שדה בתשובה לא מכיל את השם או את המייל
        dump = json.dumps(view, ensure_ascii=False)
        assert "סטודנט אחד" not in dump and "s1@" not in dump


def test_only_admin_sees_anonymous_sender(chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "שאלה", anonymous=True)
    view = _only(chat.list_messages(c, people["admin"]), mid)
    assert "סטודנט אחד" in view["sender_name"]
    assert view["sender_id"] == people["s1"].id


def test_sender_still_sees_own_anonymous_message_as_mine(chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "שאלה", anonymous=True)
    view = _only(chat.list_messages(c, people["s1"]), mid)
    assert view["mine"] and view["sender_name"] == ANONYMOUS_NAME


def test_reply_quote_keeps_anonymity(chat, people):
    c = people["course"].id
    q = chat.send(c, people["s1"], "שאלה", anonymous=True)
    a = chat.send(c, people["lecturer"], "תשובה", reply_to_id=q)
    assert _only(chat.list_messages(c, people["s2"]), a)["reply_to"]["sender_name"] == ANONYMOUS_NAME
    assert "סטודנט אחד" in _only(chat.list_messages(c, people["admin"]), a)["reply_to"]["sender_name"]


# ---------- reactions ----------
def test_reaction_add_replace_remove(db, chat, people):
    c = people["course"].id
    mid = chat.send(c, people["lecturer"], "הודעה")
    r = ReactionService(db)
    assert r.toggle(mid, people["s1"], "👍") == "👍"
    assert r.toggle(mid, people["s1"], "❤️") == "❤️"  # החלפה
    rows = db.execute("SELECT emoji FROM message_reactions WHERE message_id = ?", (mid,)).fetchall()
    assert [x["emoji"] for x in rows] == ["❤️"]
    assert r.toggle(mid, people["s1"], "❤️") is None  # הסרה
    assert db.execute("SELECT COUNT(*) FROM message_reactions").fetchone()[0] == 0


def test_reaction_summary_and_who(db, chat, people):
    c = people["course"].id
    mid = chat.send(c, people["lecturer"], "הודעה")
    r = ReactionService(db)
    r.toggle(mid, people["s1"], "👍")
    r.toggle(mid, people["s2"], "👍")
    r.toggle(mid, people["admin"], "😂")
    view = _only(chat.list_messages(c, people["s1"]), mid)
    assert view["reactions"] == {"summary": [["👍", 2], ["😂", 1]], "mine": "👍"}
    assert {w["name"] for w in r.who(mid)} == {"סטודנט אחד", "סטודנט שתיים", "אדמין"}


def test_unknown_emoji_rejected(db, chat, people):
    mid = chat.send(people["course"].id, people["s1"], "x")
    with pytest.raises(ValidationError):
        ReactionService(db).toggle(mid, people["s1"], "🔥")


def test_db_enforces_one_reaction_per_user(db, chat, people):
    import sqlite3

    mid = chat.send(people["course"].id, people["s1"], "x")
    db.execute("INSERT INTO message_reactions VALUES (?, ?, ?)", (mid, people["s2"].id, "👍"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO message_reactions VALUES (?, ?, ?)", (mid, people["s2"].id, "😂"))


# ---------- HTTP ----------
def test_outsider_cannot_read_chat(app, client):
    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    member = users.create("m@test.ac.il", "חבר", "student")
    outsider = users.create("o@test.ac.il", "זר", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll(course.id, member)
    conn.close()
    login(client, member.id)
    assert client.post(f"/api/courses/{course.id}/chat", json={"body": "היי"}).status_code == 200
    login(client, outsider.id)
    assert client.get(f"/api/courses/{course.id}/chat").status_code == 403
    assert client.post("/api/messages/1/reactions", json={"emoji": "👍"}).status_code == 403


# ---------- delete ----------
def test_sender_deletes_own_message(db, chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "טעיתי")
    ReactionService(db).toggle(mid, people["s2"], "👍")
    chat.delete(mid, people["s1"])
    view = _only(chat.list_messages(c, people["s2"]), mid)
    assert view["deleted"] and view["body"] == "" and view["reactions"]["summary"] == []
    assert not view["can_delete"]


def test_cannot_delete_others_message_but_admin_can(chat, people):
    from modelplus.errors import Forbidden

    c = people["course"].id
    mid = chat.send(c, people["s1"], "הודעה")
    with pytest.raises(Forbidden):
        chat.delete(mid, people["s2"])
    with pytest.raises(Forbidden):
        chat.delete(mid, people["lecturer"])
    chat.delete(mid, people["admin"])
    assert _only(chat.list_messages(c, people["s1"]), mid)["deleted"]


def test_can_delete_flag(chat, people):
    c = people["course"].id
    mid = chat.send(c, people["s1"], "הודעה")
    assert _only(chat.list_messages(c, people["s1"]), mid)["can_delete"]
    assert not _only(chat.list_messages(c, people["s2"]), mid)["can_delete"]
    assert _only(chat.list_messages(c, people["admin"]), mid)["can_delete"]


def test_reply_to_deleted_message_shows_placeholder(chat, people):
    c = people["course"].id
    q = chat.send(c, people["s1"], "שאלה")
    a = chat.send(c, people["s2"], "תשובה", reply_to_id=q)
    chat.delete(q, people["s1"])
    assert _only(chat.list_messages(c, people["s2"]), a)["reply_to"]["body"] == "ההודעה נמחקה"


def test_no_reactions_on_deleted_message(db, chat, people):
    mid = chat.send(people["course"].id, people["s1"], "x")
    chat.delete(mid, people["s1"])
    with pytest.raises(ValidationError):
        ReactionService(db).toggle(mid, people["s2"], "👍")


def test_deleted_poll_hides_results(db, people):
    polls = PollService(db)
    chat = ChatService(db, poll_reader=polls)
    mid = polls.create(people["course"].id, people["lecturer"], "ש", ["א", "ב"])
    chat.delete(mid, people["lecturer"])
    assert _only(chat.list_messages(people["course"].id, people["s1"]), mid)["poll"] is None


# ---------- read receipts ----------
def test_read_receipts_counts_and_blue_ticks(db, chat, people):
    from modelplus.services.chat import ReadReceiptService

    c = people["course"].id
    reads = ReadReceiptService(db)
    mid = chat.send(c, people["lecturer"], "שלום")
    r = reads.receipts_for(c, people["lecturer"])
    assert r["audience"] == 2 and r["read"][mid] == 0  # s1 ו-s2
    reads.mark_read(c, people["s1"], mid)
    assert reads.receipts_for(c, people["lecturer"])["read"][mid] == 1
    reads.mark_read(c, people["s2"], mid)
    reads.mark_read(c, people["s2"], mid)  # פעמיים לא נספר פעמיים
    assert reads.receipts_for(c, people["lecturer"])["read"][mid] == 2  # כולם קראו: וי כחול


def test_mark_read_skips_own_and_future_messages(db, chat, people):
    from modelplus.services.chat import ReadReceiptService

    c = people["course"].id
    reads = ReadReceiptService(db)
    own = chat.send(c, people["s1"], "שלי")
    first = chat.send(c, people["s2"], "1")
    later = chat.send(c, people["s2"], "2")
    reads.mark_read(c, people["s1"], first)
    rows = {r[0] for r in db.execute("SELECT message_id FROM message_reads WHERE user_id = ?", (people["s1"].id,))}
    assert rows == {first}
    assert own not in rows and later not in rows


def test_non_member_reads_are_not_counted(db, chat, people):
    from modelplus.services.chat import ReadReceiptService

    c = people["course"].id
    reads = ReadReceiptService(db)
    mid = chat.send(c, people["s1"], "x")
    reads.mark_read(c, people["admin"], mid)  # אדמין לא חבר בקורס
    assert reads.receipts_for(c, people["s1"])["read"][mid] == 0


def test_message_info_only_for_sender(db, chat, people):
    from modelplus.errors import Forbidden
    from modelplus.services.chat import ReadReceiptService

    c = people["course"].id
    reads = ReadReceiptService(db)
    mid = chat.send(c, people["s1"], "שאלה", anonymous=True)
    reads.mark_read(c, people["s2"], mid)
    info = reads.info(mid, people["s1"])
    assert [r["name"] for r in info["read_by"]] == ["סטודנט שתיים"]
    assert info["unread"] == 1 and info["audience"] == 2
    for other in (people["s2"], people["lecturer"]):
        with pytest.raises(Forbidden):
            reads.info(mid, other)


def test_migration_adds_deleted_column(tmp_path):
    import sqlite3

    from modelplus.db import connect, init_schema

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, course_id INT, sender_id INT, body TEXT, "
                "reply_to_id INT, is_anonymous INT, poll_id INT, created_at REAL, updated_at REAL)")
    old.commit()
    old.close()
    conn = connect(path)
    init_schema(conn)
    assert "deleted" in {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
