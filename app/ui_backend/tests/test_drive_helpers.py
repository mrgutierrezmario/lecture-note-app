"""Google Drive helpers that need no network: paths, token encryption, OAuth state."""

import uuid

import pytest

from integrations import google_drive as gd


def test_clean_folder_path():
    assert gd.clean_folder_path(" School / Fall 2026: Notes/ ") == "School/Fall 2026 Notes"
    assert gd.clean_folder_path("a\\b") == "a/b"
    assert gd.clean_folder_path("///") == ""
    assert gd.clean_folder_path('bad:*?"<>|chars') == "badchars"


def test_encrypt_decrypt_roundtrip_and_tamper():
    token = "1//refresh-token-value"
    blob = gd.encrypt(token)
    assert blob != token
    assert gd.decrypt(blob) == token
    with pytest.raises(gd.DriveError):
        gd.decrypt(blob[:-2] + "zz")


def test_oauth_state_is_bound_to_the_user():
    uid, other = uuid.uuid4(), uuid.uuid4()
    state = gd.make_state(uid)
    assert gd.check_state(state, uid)
    assert not gd.check_state(state, other)
    assert not gd.check_state("garbage", uid)


def test_redirect_uri_uses_public_url():
    assert gd.redirect_uri() == "https://notes.example.test/api/drive/callback"
