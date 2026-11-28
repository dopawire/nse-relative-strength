"""Login: password hashing, signed sessions, roles, lockout, CSRF header,
security headers, the users CLI."""
import time

import pytest

from backend import auth


@pytest.fixture
def users(tmp_path, monkeypatch):
    monkeypatch.setenv("NSE_RS_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("NSE_RS_SECRET", "test-secret")
    monkeypatch.setenv("NSE_RS_AUTH", "1")
    monkeypatch.setenv("NSE_RS_COOKIE_SECURE", "0")
    auth._fails.clear()
    auth.set_user("boss", "correct horse battery", "admin")
    auth.set_user("guest", "viewer password 1", "viewer")
    return tmp_path / "users.json"


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret-password")
    assert h.startswith("scrypt$") and "s3cret" not in h
    assert auth.check_password("s3cret-password", h)
    assert not auth.check_password("wrong", h)
    assert not auth.check_password("x", "garbage")
    assert auth.hash_password("same") != auth.hash_password("same")   # salted


def test_set_user_validation(users):
    for bad in (("", "long enough pw", "viewer"), ("a b", "long enough pw", "viewer"),
                ("ok", "short", "viewer"), ("ok", "long enough pw", "root")):
        with pytest.raises(ValueError):
            auth.set_user(*bad)
    assert users.stat().st_mode & 0o777 == 0o600


def test_tokens(users):
    u = auth.load_users()["boss"]
    tok = auth.make_token("boss", u)
    assert auth.read_token(tok) == {"u": "boss", "r": "admin"}
    payload, sig = tok.split(".")
    assert auth.read_token(payload + "." + sig[:-2] + "xx") is None          # tampered
    assert auth.read_token("nonsense") is None
    assert auth.read_token(tok, now=time.time() + 15 * 86400) is None      # expired
    auth.set_user("boss", "a brand new password", "admin")                 # password change
    assert auth.read_token(tok) is None
    tok2 = auth.make_token("boss", auth.load_users()["boss"])
    auth.remove_user("boss")
    assert auth.read_token(tok2) is None                                   # user removed


def test_lockout():
    auth._fails.clear()
    for _ in range(auth.MAX_FAILS):
        auth.record_failure("ip:1.2.3.4")
    assert auth.locked("ip:1.2.3.4") and not auth.locked("ip:5.6.7.8")
    assert not auth.locked("ip:1.2.3.4", now=time.time() + auth.FAIL_WINDOW + 1)
    auth.clear_failures("ip:1.2.3.4")
    assert not auth.locked("ip:1.2.3.4")


@pytest.fixture
def api(users):
    from fastapi.testclient import TestClient
    import backend.main as m
    with TestClient(m.app) as c:
        yield c


def login(c, name, pw):
    return c.post("/api/auth/login", json={"username": name, "password": pw},
                  headers={"X-NSE-RS": "1"})


def test_api_requires_login(api):
    assert api.get("/api/meta").status_code == 401
    assert api.get("/api/stock/TCS").status_code == 401
    assert api.get("/api/health").status_code == 200                     # public
    r = api.get("/api/meta")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]


def test_login_flow_and_roles(api):
    assert login(api, "boss", "wrong password").status_code == 401
    r = login(api, "guest", "viewer password 1")
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=strict" in ck
    assert api.get("/api/meta").status_code == 200
    me = api.get("/api/auth/me").json()
    assert me["user"] == "guest" and me["can"]["update_prices"] is False
    h = {"X-NSE-RS": "1"}
    assert api.post("/api/reload", headers=h).status_code == 403            # viewer: no admin actions
    assert api.put("/api/watchlist", json={"symbols": ["TCS"]}, headers=h).status_code == 403
    api.post("/api/auth/logout", headers=h)
    assert api.get("/api/meta").status_code == 401
    login(api, "boss", "correct horse battery")
    assert api.get("/api/auth/me").json()["can"]["update_prices"] is True
    assert api.post("/api/reload").status_code == 403                       # no CSRF header
    assert api.post("/api/reload", headers=h).status_code == 200


def test_login_lockout_via_api(api):
    for _ in range(auth.MAX_FAILS):
        assert login(api, "boss", "nope nope nope").status_code == 401
    r = login(api, "boss", "correct horse battery")                         # right password, still locked
    assert r.status_code == 429


def test_unknown_api_route_is_404_not_the_app(api):
    login(api, "boss", "correct horse battery")
    assert api.get("/api/does-not-exist").status_code == 404


def test_users_cli(tmp_path, monkeypatch, capsys):
    from backend import users as cli
    monkeypatch.setenv("NSE_RS_USERS", str(tmp_path / "u.json"))
    monkeypatch.setenv("NSE_RS_PASSWORD", "a long password")
    assert cli.main(["add", "eren", "--admin"]) == 0
    assert auth.load_users()["eren"]["role"] == "admin"
    v = auth.load_users()["eren"]["v"]
    monkeypatch.setenv("NSE_RS_PASSWORD", "another long password")
    cli.main(["passwd", "eren"])
    assert auth.load_users()["eren"]["v"] == v + 1
    cli.main(["list"])
    assert "eren" in capsys.readouterr().out
    cli.main(["remove", "eren"])
    assert auth.load_users() == {}


def test_head_for_uptime_monitors(api):
    from pathlib import Path
    assert api.head("/api/health").status_code == 200
    if (Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html").exists():
        assert api.head("/").status_code == 200      # the app shell (only once it's built)
