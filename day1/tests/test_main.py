from io import StringIO

from main import run


def test_main_wait_moves_piece_after_multiple_intervals():
    lines = [
        'Board:',
        'wR . .',
        '. . .',
        '. . .',
        'Commands:',
        'click 50 50',
        'click 250 50',
        'wait 1000',
        'wait 1000',
        'print board',
    ]

    output = StringIO()
    run(lines, output=output)
    assert output.getvalue().strip() == '. . wR\n. . .\n. . .'


def test_main_click_friendly_replaces_selection():
    lines = [
        'Board:',
        'wR wP .',
        '. . .',
        '. . .',
        'Commands:',
        'click 50 50',
        'click 150 50',
        'print board',
    ]

    output = StringIO()
    run(lines, output=output)
    assert output.getvalue().strip() == 'wR wP .\n. . .\n. . .'


def test_main_click_enemy_replaces_selection_and_moves():
    lines = [
        'Board:',
        'wR bP .',
        '. . .',
        '. . .',
        'Commands:',
        'click 50 50',
        'click 150 50',
        'wait 1000',
        'print board',
    ]

    output = StringIO()
    run(lines, output=output)
    assert output.getvalue().strip() == '. wR .\n. . .\n. . .'


def test_main_concurrent_moving_pieces_conflict_for_same_destination():
    lines = [
        'Board:',
        'wR . bR',
        '. . .',
        '. . .',
        'Commands:',
        'click 50 50',
        'click 150 50',
        'wait 500',
        'click 250 50',
        'click 150 50',
        'wait 500',
        'wait 500',
        'print board',
    ]

    output = StringIO()
    run(lines, output=output)
    assert output.getvalue().strip() == '. bR .\n. . .\n. . .'


def test_main_attack_piece_in_flight():
    lines = [
        'Board:',
        'wR . .',
        'bR . .',
        '. . .',
        'Commands:',
        'click 50 50',
        'click 150 50',
        'wait 500',
        'click 50 150',
        'click 50 50',
        'wait 1000',
        'print board',
    ]

    output = StringIO()
    run(lines, output=output)
    assert output.getvalue().strip() == 'bR wR .\n. . .\n. . .'
