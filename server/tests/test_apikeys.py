"""Chiavi API, area admin e intestazioni di sicurezza."""
import pytest
from fastapi.testclient import TestClient

from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph

from test_api import upper

XRW = {"X-Requested-With": "converter"}
PW = "segreta-di-prova"


def make(tmp_path, **kw):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.rebuild()
    return TestClient(create_app(Settings(work_dir=tmp_path, **kw), g))


@pytest.fixture
def client(tmp_path):
    with make(tmp_path, admin_password=PW) as c:
        yield c


def login(c):
    r = c.post("/admin/api/login", json={"password": PW}, headers=XRW)
    assert r.status_code == 200
    return r


def new_key(c, perms):
    login(c)
    r = c.post("/admin/api/keys", json={"name": "prova", "perms": perms}, headers=XRW)
    assert r.status_code == 200, r.text
    return r.json()


def api(c, method, path, key=None, **kw):
    """Chiamata come uno script: senza i cookie della pagina e dell'admin."""
    c.cookies.clear()
    headers = {"apikey": key} if key else {}
    return c.request(method, path, headers=headers, **kw)


def job(c, key=None):
    return api(c, "POST", "/api/jobs", key, data={"target": "md"}, files={"file": ("a.txt", b"ciao")})


def test_without_keys_api_stays_open(client):
    assert api(client, "GET", "/api/formats").status_code == 200
    assert job(client).status_code == 201


def test_wrong_key_401_before_upload(client):
    r = job(client, "uconv_sbagliata")
    assert r.status_code == 401
    assert not client.app.state.manager.jobs


def test_permissions(client):
    k = new_key(client, ["convert"])
    assert k["key"].startswith("uconv_") and "hash" not in k
    r = job(client, k["key"])
    assert r.status_code == 201
    jid = r.json()["id"]
    r = api(client, "GET", f"/api/jobs/{jid}", k["key"])
    assert r.status_code == 403 and "jobs" in r.json()["detail"]
    assert api(client, "GET", "/api/formats", k["key"]).status_code == 403
    # aggiungo il permesso
    login(client)
    assert client.put(f"/admin/api/keys/{k['id']}", json={"perms": ["convert", "jobs"]}, headers=XRW).status_code == 200
    assert api(client, "GET", f"/api/jobs/{jid}", k["key"]).status_code == 200
    # ultimo uso registrato, hash salvato al posto della chiave
    login(client)
    rec = client.get("/admin/api/keys").json()["keys"][0]
    assert rec["last_used"] and rec["perms"] == ["convert", "jobs"]
    stored = (client.app.state.keys.file).read_text()
    assert k["key"] not in stored
    # revoca
    assert client.delete(f"/admin/api/keys/{k['id']}", headers=XRW).status_code == 200
    assert job(client, k["key"]).status_code == 401


def test_require_key_toggle(client):
    login(client)
    r = client.put("/admin/api/settings", json={"require_key": True}, headers=XRW)
    assert r.status_code == 200 and r.json()["require_key"]
    r = job(client)
    assert r.status_code == 401 and "apikey" in r.json()["detail"]
    assert api(client, "GET", "/api/formats").status_code == 401
    assert api(client, "GET", "/healthz").status_code == 200
    # la pagina web funziona con il suo cookie di sessione
    client.cookies.clear()
    client.get("/")
    assert client.get("/api/formats").status_code == 200
    assert client.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x")}).status_code == 201
    # cookie di sessione falso
    client.cookies.clear()
    client.cookies.set("uconv_session", "9999999999.abc")
    assert client.get("/api/formats").status_code == 401
    # spento di nuovo
    login(client)
    client.put("/admin/api/settings", json={"require_key": False}, headers=XRW)
    assert job(client).status_code == 201


def test_require_key_survives_restart(tmp_path):
    with make(tmp_path, admin_password=PW) as c:
        login(c)
        c.put("/admin/api/settings", json={"require_key": True}, headers=XRW)
    with make(tmp_path, admin_password=PW) as c:
        assert job(c).status_code == 401


def test_admin_protection(client):
    assert client.get("/admin/api/keys").status_code == 401
    assert client.post("/admin/api/login", json={"password": "no"}, headers=XRW).status_code == 401
    assert client.post("/admin/api/login", json={"password": PW}).status_code == 403  # senza X-Requested-With
    login(client)
    assert client.post("/admin/api/keys", json={"name": "x", "perms": ["convert"]}).status_code == 403
    assert client.post("/admin/api/keys", json={"name": "x", "perms": ["boh"]}, headers=XRW).status_code == 400
    assert client.post("/admin/api/keys", json={"name": " ", "perms": ["convert"]}, headers=XRW).status_code == 400


def test_admin_login_lockout(client):
    for _ in range(5):
        client.post("/admin/api/login", json={"password": "no"}, headers=XRW)
    assert client.post("/admin/api/login", json={"password": PW}, headers=XRW).status_code == 429


def test_admin_login_toggle(client):
    login(client)
    assert client.put("/admin/api/settings", json={"admin_login": False}, headers=XRW).status_code == 200
    client.cookies.clear()
    assert client.get("/admin/api/keys").status_code == 200
    assert client.put("/admin/api/settings", json={"admin_login": True}, headers=XRW).status_code == 200
    client.cookies.clear()
    assert client.get("/admin/api/keys").status_code == 401


def test_admin_disabled_without_password(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/admin/api/state").json()["enabled"] is False
        assert c.get("/admin/api/keys").status_code == 404
        assert c.post("/admin/api/login", json={"password": ""}, headers=XRW).status_code == 404


def test_password_from_file(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "admin-password").write_text(PW + "\n")
    with make(tmp_path) as c:
        login(c)


def test_cross_site_and_headers(client):
    r = client.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x")},
                    headers={"Origin": "https://altro.example"})
    assert r.status_code == 403
    r = client.get("/")
    assert "uconv_session" in r.headers.get("set-cookie", "")
    assert r.headers["X-Frame-Options"] == "DENY" and "script-src 'self' 'sha256-" in r.headers["Content-Security-Policy"]
    assert client.get("/admin").status_code == 200
    assert client.get("/apidocs").status_code == 200
    spec = client.get("/apidocs/openapi.json").json()
    assert "apikey" in str(spec["components"]["securitySchemes"])
    assert "/admin/api/keys" not in spec["paths"] and "/api/jobs" in spec["paths"]
