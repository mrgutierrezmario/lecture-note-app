"""Passwords and the signed login token."""

import time
import uuid

from accounts import auth


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse")
    assert h != "correct horse"
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)


def test_token_roundtrip_and_tamper():
    uid = uuid.uuid4()
    token = auth.make_token(uid)
    assert auth.parse_token(token) == uid
    # Flip a character in the signature: rejected.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert auth.parse_token(tampered) is None
    # A different user id with the original signature: rejected.
    parts = token.split(":")
    forged = f"{uuid.uuid4()}:{parts[1]}:{parts[2]}"
    assert auth.parse_token(forged) is None


def test_expired_token_rejected():
    uid = uuid.uuid4()
    expires = int(time.time()) - 10
    payload = f"{uid}:{expires}"
    token = f"{payload}:{auth._sign(payload)}"
    assert auth.parse_token(token) is None


def test_garbage_tokens():
    assert auth.parse_token("") is None
    assert auth.parse_token("not-a-token") is None
    assert auth.parse_token("a:b:c") is None
