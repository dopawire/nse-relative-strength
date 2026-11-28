"""Login for the private site: users, password hashes, signed session cookies.

Standard library only (no extra dependency to audit):

  passwords   hashlib.scrypt (n=2**14, r=8, p=1), random 16-byte salt,
              compared with hmac.compare_digest
  sessions    an HMAC-SHA256-signed cookie "<payload>.<sig>" — payload is
              {"u": user, "r": role, "x": expiry, "v": password version}; a
              password change bumps the version and ends old sessions
  secret      NSE_RS_SECRET, else a random key kept in <data dir>/.secret_key
              (created 0600 on first use)
  users       <data dir>/users.json (NSE_RS_USERS overrides), managed with
              `python -m backend.users add|passwd|remove|list`
  lockout     10 failed logins from one address or for one user within 15
              minutes → refused for the rest of that window

NSE_RS_AUTH=0 switches login off (local development on 127.0.0.1 only).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from rs_engine.config import DATA_DIR

COOKIE = "nse_rs_session"
SESSION_DAYS = int(os.environ.get("NSE_RS_SESSION_DAYS", "14"))
ROLES = ("admin", "viewer")
MAX_FAILS, FAIL_WINDOW = 10, 15 * 60

_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def enabled():
    return os.environ.get("NSE_RS_AUTH", "1") != "0"


def users_path():
    return os.environ.get("NSE_RS_USERS") or os.path.join(DATA_DIR, "users.json")


# ---------------------------------------------------------------- passwords
def hash_password(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def check_password(pw, stored):
    try:
        algo, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        want = base64.b64decode(dk)
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1,
                             dklen=len(want))
        return hmac.compare_digest(got, want)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- user store
def load_users(path=None):
    path = path or users_path()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_users(users, path=None):
    path = path or users_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def valid_username(name):
    return bool(name) and len(name) <= 64 and all(c.isalnum() or c in "._-@" for c in name)


def set_user(name, password, role="viewer", path=None):
    if not valid_username(name):
        raise ValueError("username: letters, digits and . _ - @ only, up to 64 characters")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    users = load_users(path)
    old = users.get(name, {})
    users[name] = {"hash": hash_password(password), "role": role,
                   "v": old.get("v", 0) + 1, "created": old.get("created", int(time.time()))}
    save_users(users, path)


def remove_user(name, path=None):
    users = load_users(path)
    if name not in users:
        return False
    del users[name]
    save_users(users, path)
    return True


def authenticate(name, password, path=None):
    """The user record when the password matches, else None (constant work
    for unknown users, so timing doesn't reveal which names exist)."""
    u = load_users(path).get(name)
    if u is None:
        check_password(password, hash_password("dummy-password"))
        return None
    return u if check_password(password, u["hash"]) else None


# ---------------------------------------------------------------- sessions
def _secret():
    env = os.environ.get("NSE_RS_SECRET")
    if env:
        return env.encode()
    path = os.path.join(DATA_DIR, ".secret_key")
    with _lock:
        if not os.path.exists(path):
            os.makedirs(DATA_DIR, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        with open(path) as f:
            return f.read().strip().encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(name, user, now=None):
    now = now or time.time()
    payload = _b64(json.dumps({"u": name, "r": user["role"], "v": user.get("v", 1),
                               "x": int(now + SESSION_DAYS * 86400)}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token, path=None, now=None):
    """{"u", "r"} for a valid, unexpired token of a user who still exists with
    the same password version — else None."""
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, AttributeError):
        return None
    if data.get("x", 0) < (now or time.time()):
        return None
    u = load_users(path).get(data.get("u"))
    if u is None or u.get("v", 1) != data.get("v"):
        return None
    return {"u": data["u"], "r": u["role"]}


# ---------------------------------------------------------------- lockout
def _recent(key, now):
    return [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]


def locked(*keys, now=None):
    now = now or time.time()
    with _lock:
        return any(len(_recent(k, now)) >= MAX_FAILS for k in keys)


def record_failure(*keys, now=None):
    now = now or time.time()
    with _lock:
        for k in keys:
            _fails[k] = _recent(k, now) + [now]


def clear_failures(*keys):
    with _lock:
        for k in keys:
            _fails.pop(k, None)
