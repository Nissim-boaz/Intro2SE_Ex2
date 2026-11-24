import gzip
import re


def test_static_files_get_a_version_and_a_year_of_caching(client):
    page = client.get("/login").get_data(as_text=True)
    url = re.search(r'href="(/static/css/app\.css\?v=\d+)"', page).group(1)
    r = client.get(url)
    assert r.status_code == 200 and "immutable" in r.headers["Cache-Control"] and "max-age=31536000" in r.headers["Cache-Control"]
    plain = client.get("/static/css/app.css")  # an address without a version is not cached forever
    assert "immutable" not in plain.headers.get("Cache-Control", "")


def test_text_is_sent_compressed_when_the_browser_accepts_it(client):
    page = client.get("/login").get_data(as_text=True)
    url = re.search(r'src="(/static/js/ui\.js\?v=\d+)"', page).group(1)
    plain = client.get(url).data
    r = client.get(url, headers={"Accept-Encoding": "gzip, deflate, br"})
    assert r.headers["Content-Encoding"] == "gzip" and gzip.decompress(r.data) == plain
    assert len(r.data) < len(plain) / 2
    assert "Accept-Encoding" in r.headers["Vary"]
    assert "Content-Encoding" not in client.get(url).headers  # no gzip asked for, none sent
    html = client.get("/login", headers={"Accept-Encoding": "gzip"})
    assert html.headers["Content-Encoding"] == "gzip" and "Moodle" in gzip.decompress(html.data).decode()
