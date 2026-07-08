from commands import ClickCommand, JumpCommand, PrintBoardCommand, WaitCommand, parse_commands


def test_parse_valid_commands():
    lines = [
        'Commands:',
        'click 50 50',
        'wait 200',
        'print board',
    ]

    commands = parse_commands(lines)
    assert len(commands) == 3
    assert isinstance(commands[0], ClickCommand)
    assert commands[0].x == 50 and commands[0].y == 50
    assert isinstance(commands[1], WaitCommand)
    assert commands[1].ms == 200
    assert isinstance(commands[2], PrintBoardCommand)


def test_parse_commands_skips_empty_lines():
    lines = [
        'Commands:',
        '',
        'click 10 20',
    ]

    commands = parse_commands(lines)
    assert len(commands) == 1
    assert isinstance(commands[0], ClickCommand)


def test_parse_commands_invalid_click_argument_count():
    lines = [
        'Commands:',
        'click 50',
    ]

    assert parse_commands(lines) == []


def test_parse_commands_invalid_wait_argument_count():
    lines = [
        'Commands:',
        'wait',
    ]

    assert parse_commands(lines) == []


def test_parse_commands_unknown_command_ignored():
    lines = [
        'Commands:',
        'fly 1 2',
    ]

    assert parse_commands(lines) == []


def test_parse_valid_jump_command():
    lines = [
        'Commands:',
        'jump 50 100',
    ]

    commands = parse_commands(lines)
    assert len(commands) == 1
    assert isinstance(commands[0], JumpCommand)
    assert commands[0].x == 50 and commands[0].y == 100


def test_parse_commands_no_commands_marker_returns_empty_list():
    lines = [
        'click 50 50',
        'wait 100',
    ]

    assert parse_commands(lines) == []
