"""Manage the site's logins.

    python -m backend.users add NAME [--admin]   # prompts for the password
    python -m backend.users passwd NAME          # new password, ends its sessions
    python -m backend.users remove NAME
    python -m backend.users list

In Docker:  docker compose exec web python -m backend.users add you --admin

Admins can also run the price update and edit the alert watchlist; viewers
only read.  Passwords: at least 10 characters.  NSE_RS_PASSWORD supplies the
password non-interactively (scripts / first-run setup).
"""
import argparse
import getpass
import os
import sys

from backend import auth


def _password():
    pw = os.environ.get("NSE_RS_PASSWORD")
    if pw:
        return pw
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("passwords don't match")
    return pw


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m backend.users", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add or replace a user")
    a.add_argument("name")
    a.add_argument("--admin", action="store_true", help="may run updates and edit the watchlist")
    p = sub.add_parser("passwd", help="set a new password (signs the user out everywhere)")
    p.add_argument("name")
    r = sub.add_parser("remove", help="delete a user")
    r.add_argument("name")
    sub.add_parser("list", help="list users")
    args = ap.parse_args(argv)

    users = auth.load_users()
    try:
        if args.cmd == "add":
            auth.set_user(args.name, _password(), "admin" if args.admin else "viewer")
            print(f"saved {args.name} ({'admin' if args.admin else 'viewer'}) → {auth.users_path()}")
        elif args.cmd == "passwd":
            if args.name not in users:
                sys.exit(f"no such user: {args.name}")
            auth.set_user(args.name, _password(), users[args.name]["role"])
            print(f"password changed for {args.name}; old sessions are signed out")
        elif args.cmd == "remove":
            print("removed" if auth.remove_user(args.name) else f"no such user: {args.name}")
        else:
            if not users:
                print(f"no users yet — add one: python -m backend.users add NAME --admin "
                      f"({auth.users_path()})")
            for name, u in sorted(users.items()):
                print(f"{name:24} {u['role']}")
    except ValueError as e:
        sys.exit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
