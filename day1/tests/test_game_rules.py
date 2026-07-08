from rules.game_rules import is_winning_capture


def test_is_winning_capture_for_king():
    assert is_winning_capture('wK')


def test_is_winning_capture_for_non_king():
    assert not is_winning_capture('wQ')


def test_is_winning_capture_for_empty_cell():
    assert not is_winning_capture('.')
