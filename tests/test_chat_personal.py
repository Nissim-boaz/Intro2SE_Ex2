import io

import pytest
from werkzeug.datastructures import FileStorage

from moodleplus.errors import ValidationError
from moodleplus.services.chat import ChatService
from moodleplus.services.chat_themes import ChatThemeService
from moodleplus.services.content import FileStore
from moodleplus.services.courses import CourseService, EnrollmentService
from moodleplus.services.polls import PollService
from tests.conftest import login

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def chat(db):
    return ChatService(db, poll_reader=PollService(db))


@pytest.fixture
def themes(db, tmp_path):
    return ChatThemeService(db, FileStore(str(tmp_path / "files")))


@pytest.fixture
def two_courses(db, people):
    other = CourseService(db).create("מבני נתונים")
    EnrollmentService(db).enroll_many(other.id, [people["s1"]])
    return people["course"].id, other.id


# ---------- stars ----------
def test_stars_are_personal(chat, people):
    c = people["course"].id
    first = chat.send(c, people["s2"], "חשוב: המבחן ב-3 בפברואר")
    chat.send(c, people["s2"], "סתם הודעה")
    chat.set_star(first, people["s1"], True)
    views = {m["id"]: m for m in chat.list_messages(c, people["s1"])}
    assert views[first]["starred"] and not [m for m in views.values() if m["id"] != first and m["starred"]]
    assert not {m["id"]: m for m in chat.list_messages(c, people["s2"])}[first]["starred"]  # nobody else sees it
    assert [r["id"] for r in chat.starred(c, people["s1"])] == [first] and chat.starred(c, people["s2"]) == []
    chat.set_star(first, people["s1"], False)
    assert chat.starred(c, people["s1"]) == []


def test_starred_list_keeps_anonymity_and_skips_deleted(chat, people):
    c = people["course"].id
    anon = chat.send(c, people["s2"], "שאלה אנונימית", anonymous=True)
    gone = chat.send(c, people["s2"], "תימחק")
    for mid in (anon, gone):
        chat.set_star(mid, people["s1"], True)
    chat.delete(gone, people["s2"])
    rows = chat.starred(c, people["s1"])
    assert [r["id"] for r in rows] == [anon] and rows[0]["sender_name"] != people["s2"].name
    with pytest.raises(ValidationError):
        chat.set_star(gone, people["s1"], True)


# ---------- the look ----------
def test_theme_defaults_and_scope(themes, people, two_courses):
    c1, c2 = two_courses
    s1 = people["s1"]
    t = themes.get(s1, c1)
    assert (t.wallpaper, t.bubble, t.custom_here) == ("doodles", "brand", False)
    themes.save(s1, c1, everywhere=False, wallpaper="mint", bubble="green")
    assert (themes.get(s1, c1).wallpaper, themes.get(s1, c1).bubble, themes.get(s1, c1).custom_here) == ("mint", "green", True)
    assert themes.get(s1, c2).wallpaper == "doodles"  # only that chat
    themes.save(s1, c2, everywhere=True, bubble="purple")
    assert themes.get(s1, c2).bubble == "purple"
    assert themes.get(s1, c1).bubble == "purple"     # "all my chats" also replaces the colour this chat had
    assert themes.get(s1, c1).wallpaper == "mint"    # ...and leaves the wallpaper it didn't touch
    assert themes.get(people["s2"], c1).bubble == "brand"  # other people keep theirs
    themes.reset(s1, c1, everywhere=False)
    assert (themes.get(s1, c1).wallpaper, themes.get(s1, c1).bubble) == ("doodles", "purple")
    themes.reset(s1, c1, everywhere=True)
    assert themes.get(s1, c2).bubble == "brand"
    for bad in ({"wallpaper": "neon"}, {"bubble": "gold"}, {"wallpaper": "image"}):
        with pytest.raises(ValidationError):
            themes.save(s1, c1, everywhere=False, **bad)


def test_photo_wallpaper_replaces_old_files(themes, people, two_courses):
    c1, _ = two_courses
    s1 = people["s1"]
    with pytest.raises(ValidationError):
        themes.save(s1, c1, False, wallpaper="image", image_name="x.exe", image=FileStorage(io.BytesIO(b"MZ"), "x.exe"))
    first = themes.save(s1, c1, False, wallpaper="image", image_name="a.png", image=FileStorage(io.BytesIO(PNG), "a.png"))
    old = themes.image_file(s1, c1)
    assert first.wallpaper == "image" and old.exists()
    second = themes.save(s1, c1, False, wallpaper="image", image_name="b.png", image=FileStorage(io.BytesIO(PNG), "b.png"))
    assert not old.exists() and second.image_version > first.image_version
    themes.save(s1, c1, False, wallpaper="sky")
    assert themes.image_file(s1, c1) is None


def test_routes(app, client):
    from moodleplus.db import connect
    from moodleplus.services.users import UserService

    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    s1 = users.create("s1@test.ac.il", "סטודנטית", "student")
    s2 = users.create("s2@test.ac.il", "סטודנט", "student")
    outsider = users.create("o@test.ac.il", "זר", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [s1, s2])
    mid = ChatService(conn).send(course.id, s2, "שימו לב")
    conn.close()

    login(client, s1.id)
    assert client.post(f"/api/messages/{mid}/star", json={"starred": True}).get_json()["starred"]
    assert [r["id"] for r in client.get(f"/api/courses/{course.id}/chat/starred").get_json()["results"]] == [mid]
    r = client.post(f"/api/courses/{course.id}/chat/theme", json={"scope": "here", "wallpaper": "rose", "bubble": "teal"})
    assert r.get_json()["wallpaper"] == "rose"
    page = client.get(f"/courses/{course.id}/chat").get_data(as_text=True)
    assert 'data-wall="rose" data-bubble="teal"' in page
    r = client.post(f"/api/courses/{course.id}/chat/theme", data={"scope": "all", "wallpaper": "image",
                    "image": (io.BytesIO(PNG), "me.png")}, content_type="multipart/form-data")
    url = r.get_json()["image_url"]
    assert url and client.get(url).data == PNG
    login(client, s2.id)  # nobody else gets my photo or my stars
    assert client.get(url).status_code == 404
    assert client.get(f"/api/courses/{course.id}/chat/starred").get_json()["results"] == []
    login(client, outsider.id)
    assert client.post(f"/api/messages/{mid}/star", json={"starred": True}).status_code == 403


def test_chat_opens_inside_the_course_page(app, client):
    from moodleplus.db import connect
    from moodleplus.services.users import UserService

    conn = connect(app.config["DATABASE"])
    users = UserService(conn)
    s1 = users.create("a@test.ac.il", "סטודנטית", "student")
    s2 = users.create("b@test.ac.il", "סטודנט", "student")
    course = CourseService(conn).create("קורס")
    EnrollmentService(conn).enroll_many(course.id, [s1, s2])
    ChatService(conn).send(course.id, s2, "שלום")
    conn.close()
    login(client, s1.id)
    page = client.get(f"/courses/{course.id}").get_data(as_text=True)
    assert "data-chat-open" in page and "chat_sheet.js" in page
    embedded = client.get(f"/courses/{course.id}/chat?embed=1").get_data(as_text=True)
    assert "chat-embedded" in embedded and "chat-embedded" not in client.get(f"/courses/{course.id}/chat").get_data(as_text=True)
    assert client.get(f"/api/courses/{course.id}/chat/unread").get_json()["unread"] == 1
