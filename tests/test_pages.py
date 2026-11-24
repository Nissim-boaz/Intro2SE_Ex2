from tests.conftest import login


def test_privacy_and_terms_are_open_to_everyone(client):
    for path, title in (("/privacy", "Privacy Policy"), ("/terms", "Terms of Service")):
        r = client.get(path)  # not signed in
        assert r.status_code == 200
        page = r.get_data(as_text=True)
        assert title in page and 'lang="en" dir="ltr"' in page
        assert "admin@test.ac.il" in page  # the contact comes from ADMIN_EMAIL


def test_login_page_links_to_them(client):
    page = client.get("/login").get_data(as_text=True)
    assert 'href="/privacy"' in page and 'href="/terms"' in page


def test_signed_in_users_see_them_too(app, client):
    from moodleplus.db import connect
    from moodleplus.services.users import UserService

    conn = connect(app.config["DATABASE"])
    stud = UserService(conn).create("p@test.ac.il", "סטודנטית", "student")
    conn.close()
    login(client, stud.id)
    assert client.get("/privacy").status_code == 200 and "Back to Moodle+" in client.get("/terms").get_data(as_text=True)
    assert 'lang="he" dir="rtl"' in client.get("/").get_data(as_text=True)  # the rest of the site stays Hebrew
