"""Passkey-Login (WebAuthn), Sessions, Einladungslinks."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Response
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from . import config, db

COOKIE = "sid"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- Rate-Limit (pro IP, im Speicher) ----------
_hits: dict[str, deque] = defaultdict(deque)
LIMIT, WINDOW = 30, 300


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def rate_limit(request: Request):
    ip, now = client_ip(request), time.time()
    q = _hits[ip]
    while q and q[0] < now - WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        raise HTTPException(429, "Zu viele Versuche. Bitte später erneut versuchen.")
    q.append(now)


# ---------- Sessions ----------
def create_session(response: Response, user_id: int):
    token = secrets.token_urlsafe(32)
    exp = int(time.time()) + config.SESSION_DAYS * 86400
    with db.tx() as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        con.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)",
                    (_hash(token), user_id, exp))
    response.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=not config.DEV, samesite="strict", path="/")


def user_from_request(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with db.tx() as con:
        row = con.execute(
            "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash=? AND s.expires_at > ?", (_hash(token), int(time.time()))).fetchone()
    return dict(row) if row else None


def require_user(request: Request) -> dict:
    u = user_from_request(request)
    if not u:
        raise HTTPException(401, "Nicht angemeldet")
    return u


def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db.tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
    response.delete_cookie(COOKIE, path="/")


# ---------- Einladungen (nur per CLI erzeugt) ----------
def create_invite(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = int(time.time()) + config.INVITE_MINUTES * 60
    with db.tx() as con:
        con.execute("DELETE FROM invites WHERE expires_at < ? OR used = 1", (int(time.time()),))
        con.execute("INSERT INTO invites(token_hash, user_id, expires_at) VALUES (?,?,?)",
                    (_hash(token), user_id, exp))
    return token


def _invite(con, token: str):
    row = con.execute("SELECT i.*, u.name, u.handle FROM invites i JOIN users u ON u.id=i.user_id "
                      "WHERE i.token_hash=? AND i.used=0 AND i.expires_at > ?",
                      (_hash(token or ""), int(time.time()))).fetchone()
    if not row:
        raise HTTPException(400, "Der Einladungslink ist ungültig oder abgelaufen.")
    return row


def registration_options(token: str) -> str:
    with db.tx() as con:
        inv = _invite(con, token)
        existing = con.execute("SELECT id FROM credentials WHERE user_id=?", (inv["user_id"],)).fetchall()
        opts = generate_registration_options(
            rp_id=config.RP_ID,
            rp_name=config.RP_NAME,
            user_name=inv["name"],
            user_id=inv["handle"],
            user_display_name=inv["name"],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["id"]))
                                 for r in existing],
        )
        con.execute("UPDATE invites SET challenge=? WHERE token_hash=?", (opts.challenge, _hash(token)))
    return options_to_json(opts)


def registration_verify(token: str, credential: dict, label: str | None) -> int:
    with db.tx() as con:
        inv = _invite(con, token)
        if not inv["challenge"]:
            raise HTTPException(400, "Keine laufende Registrierung.")
        try:
            v = verify_registration_response(
                credential=credential,
                expected_challenge=inv["challenge"],
                expected_rp_id=config.RP_ID,
                expected_origin=config.ORIGIN,
                require_user_verification=True,
            )
        except Exception as e:
            raise HTTPException(400, f"Registrierung fehlgeschlagen: {e}")
        con.execute("INSERT INTO credentials(id, user_id, public_key, sign_count, label) VALUES (?,?,?,?,?)",
                    (bytes_to_base64url(v.credential_id), inv["user_id"], v.credential_public_key,
                     v.sign_count, (label or "")[:60] or None))
        con.execute("UPDATE invites SET used=1 WHERE token_hash=?", (_hash(token),))
        return inv["user_id"]


def login_options() -> dict:
    opts = generate_authentication_options(rp_id=config.RP_ID,
                                           user_verification=UserVerificationRequirement.REQUIRED)
    cid = secrets.token_urlsafe(16)
    with db.tx() as con:
        con.execute("DELETE FROM challenges WHERE expires_at < ?", (int(time.time()),))
        con.execute("INSERT INTO challenges(id, challenge, expires_at) VALUES (?,?,?)",
                    (cid, opts.challenge, int(time.time()) + 300))
    return {"challengeId": cid, "options": json.loads(options_to_json(opts))}


def login_verify(challenge_id: str, credential: dict) -> int:
    with db.tx() as con:
        ch = con.execute("SELECT challenge FROM challenges WHERE id=? AND expires_at > ?",
                         (challenge_id, int(time.time()))).fetchone()
        con.execute("DELETE FROM challenges WHERE id=?", (challenge_id,))
        if not ch:
            raise HTTPException(400, "Anmeldung abgelaufen, bitte erneut versuchen.")
        cred = con.execute("SELECT * FROM credentials WHERE id=?", (credential.get("id", ""),)).fetchone()
        if not cred:
            raise HTTPException(401, "Dieser Passkey ist nicht bekannt.")
        try:
            v = verify_authentication_response(
                credential=credential,
                expected_challenge=ch["challenge"],
                expected_rp_id=config.RP_ID,
                expected_origin=config.ORIGIN,
                credential_public_key=cred["public_key"],
                credential_current_sign_count=cred["sign_count"],
                require_user_verification=True,
            )
        except Exception as e:
            raise HTTPException(401, f"Anmeldung fehlgeschlagen: {e}")
        con.execute("UPDATE credentials SET sign_count=?, last_used=datetime('now') WHERE id=?",
                    (v.new_sign_count, cred["id"]))
        return cred["user_id"]
