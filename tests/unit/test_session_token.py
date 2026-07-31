from server.accounts import issue_session_token, verify_session_token

_SECRET = b"unit-test-secret"


def test_a_freshly_issued_token_verifies_for_the_same_username():
    token = issue_session_token("alice", _SECRET, ttl_s=3600)
    assert verify_session_token("alice", token, _SECRET) is True


def test_a_token_does_not_verify_for_a_different_username():
    token = issue_session_token("alice", _SECRET, ttl_s=3600)
    assert verify_session_token("bob", token, _SECRET) is False


def test_a_token_does_not_verify_against_a_different_secret():
    token = issue_session_token("alice", _SECRET, ttl_s=3600)
    assert verify_session_token("alice", token, b"a-different-secret") is False


def test_an_already_expired_token_does_not_verify():
    token = issue_session_token("alice", _SECRET, ttl_s=-1)
    assert verify_session_token("alice", token, _SECRET) is False


def test_a_tampered_signature_does_not_verify():
    token = issue_session_token("alice", _SECRET, ttl_s=3600)
    expiry, _, signature = token.partition(".")
    flipped_first_char = "0" if signature[0] != "0" else "1"
    tampered = f"{expiry}.{flipped_first_char}{signature[1:]}"

    assert verify_session_token("alice", tampered, _SECRET) is False


def test_a_missing_token_does_not_verify():
    assert verify_session_token("alice", None, _SECRET) is False


def test_a_malformed_token_does_not_verify():
    assert verify_session_token("alice", "not-a-real-token", _SECRET) is False
    assert verify_session_token("alice", "not-an-int.deadbeef", _SECRET) is False
