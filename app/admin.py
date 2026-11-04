"""Verwaltung per SSH, z. B.:

    docker compose exec app python -m app.admin create-user marco
    docker compose exec app python -m app.admin add-passkey marco
    docker compose exec app python -m app.admin list
    docker compose exec app python -m app.admin remove-passkey <id>
    docker compose exec app python -m app.admin delete-user marco
"""
import argparse
import secrets
import sys

from . import auth, config, db


def _link(token: str) -> str:
    return f"{config.ORIGIN}/register?token={token}"


def _user(con, name):
    u = con.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
    if not u:
        sys.exit(f"Benutzer '{name}' gibt es nicht.")
    return u["id"]


def main():
    db.init()
    ap = argparse.ArgumentParser(prog="python -m app.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-user").add_argument("name")
    sub.add_parser("add-passkey").add_argument("name")
    sub.add_parser("delete-user").add_argument("name")
    sub.add_parser("remove-passkey").add_argument("id")
    sub.add_parser("list")
    a = ap.parse_args()

    if a.cmd == "create-user":
        with db.tx() as con:
            if con.execute("SELECT 1 FROM users WHERE name=?", (a.name,)).fetchone():
                sys.exit(f"Benutzer '{a.name}' existiert bereits. Nutze add-passkey.")
            cur = con.execute("INSERT INTO users(name, handle) VALUES (?,?)", (a.name, secrets.token_bytes(32)))
            uid = cur.lastrowid
            con.execute("INSERT INTO settings(user_id) VALUES (?)", (uid,))
        print(f"Benutzer '{a.name}' angelegt.")
        print(f"Passkey-Link (gültig {config.INVITE_MINUTES} Minuten):\n{_link(auth.create_invite(uid))}")
    elif a.cmd == "add-passkey":
        with db.tx() as con:
            uid = _user(con, a.name)
        print(f"Passkey-Link für '{a.name}' (gültig {config.INVITE_MINUTES} Minuten):\n"
              f"{_link(auth.create_invite(uid))}")
    elif a.cmd == "delete-user":
        with db.tx() as con:
            uid = _user(con, a.name)
            con.execute("DELETE FROM users WHERE id=?", (uid,))
        print(f"Benutzer '{a.name}' samt Depotdaten gelöscht.")
    elif a.cmd == "remove-passkey":
        with db.tx() as con:
            n = con.execute("DELETE FROM credentials WHERE id=?", (a.id,)).rowcount
        print("Passkey entfernt." if n else "Passkey nicht gefunden.")
    elif a.cmd == "list":
        with db.tx() as con:
            for u in con.execute("SELECT id, name, created_at FROM users ORDER BY name"):
                print(f"{u['name']} (angelegt {u['created_at']})")
                for c in con.execute("SELECT id, label, created_at, last_used FROM credentials WHERE user_id=?",
                                     (u["id"],)):
                    print(f"  Passkey {c['id']}  {c['label'] or ''}  angelegt {c['created_at']}  "
                          f"zuletzt {c['last_used'] or 'nie'}")


if __name__ == "__main__":
    main()
