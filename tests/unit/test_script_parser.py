from texttests.script_parser import Command, parse_line


def test_parse_line_splits_the_command_name_from_its_arguments():
    command = parse_line("click 50 150")

    assert command == Command(name="click", args=["50", "150"])


def test_parse_line_handles_a_single_word_command():
    command = parse_line("wait 1000")

    assert command == Command(name="wait", args=["1000"])


def test_parse_line_keeps_multi_word_arguments_separate():
    command = parse_line("print board")

    assert command == Command(name="print", args=["board"])


def test_parse_line_returns_none_for_a_blank_line():
    assert parse_line("") is None
    assert parse_line("   ") is None


def test_parse_line_has_no_knowledge_of_any_specific_command():
    # a made-up command name is tokenized exactly like a real one - parse_line
    # doesn't know or care what commands exist, only the runner does.
    command = parse_line("teleport 50 50")

    assert command == Command(name="teleport", args=["50", "50"])
