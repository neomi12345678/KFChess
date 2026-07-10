from texttests.script_parser import (
    AssertPrintBoardInstruction,
    ClickInstruction,
    JumpInstruction,
    SetBoardInstruction,
    WaitInstruction,
    parse,
)


def test_parse_reads_a_board_block_into_a_set_board_instruction():
    instructions = parse("Board\nwK . .\n. . .\n")

    assert instructions == [SetBoardInstruction(rows=["wK . .", ". . ."])]


def test_parse_reads_click_command():
    instructions = parse("click 50 150")

    assert instructions == [ClickInstruction(x=50, y=150)]


def test_parse_reads_jump_command():
    instructions = parse("jump 50 150")

    assert instructions == [JumpInstruction(x=50, y=150)]


def test_parse_reads_wait_command():
    instructions = parse("wait 1000")

    assert instructions == [WaitInstruction(ms=1000)]


def test_parse_reads_print_board_block_into_an_assertion():
    instructions = parse("print board\nwK . .\n. . .\n")

    assert instructions == [AssertPrintBoardInstruction(expected_rows=["wK . .", ". . ."])]


def test_parse_ignores_blank_lines_between_instructions():
    instructions = parse("click 50 50\n\nwait 1000")

    assert instructions == [ClickInstruction(x=50, y=50), WaitInstruction(ms=1000)]


def test_parse_ignores_unrecognized_lines():
    instructions = parse("this is a comment, not a command\nclick 50 50")

    assert instructions == [ClickInstruction(x=50, y=50)]
