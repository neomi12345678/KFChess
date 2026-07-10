import io

from main import main, run


def test_run_prints_the_board_when_there_are_no_commands():
    output = run("Board:\nwK . .\n. . .\n. . .\nCommands:\n")

    assert output == ""


def test_run_executes_print_board_command():
    output = run("Board:\nwK . .\n. . .\n. . .\nCommands:\nprint board\n")

    assert output == "wK . .\n. . .\n. . ."


def test_run_executes_click_and_wait_commands_before_printing():
    output = run(
        "Board:\nwK . .\n. . .\n. . .\nCommands:\nclick 50 50\nclick 150 150\nwait 1000\nprint board\n"
    )

    assert output == ". . .\n. wK .\n. . ."


def test_run_executes_jump_command():
    output = run("Board:\n. wK .\n. . .\nCommands:\njump 150 50\nwait 1000\nprint board\n")

    assert output == ". wK .\n. . ."


def test_run_reports_unknown_token_as_a_structured_error():
    output = run("Board:\nwK xZ\n. .\nCommands:\n")

    assert output == "ERROR UNKNOWN_TOKEN"


def test_run_reports_row_width_mismatch_as_a_structured_error():
    output = run("Board:\nwK . .\n. bK\nCommands:\n")

    assert output == "ERROR ROW_WIDTH_MISMATCH"


def test_run_supports_multiple_print_board_commands():
    output = run("Board:\nwR . .\nCommands:\nclick 50 50\nclick 250 50\nwait 1000\nprint board\nwait 1000\nprint board\n")

    assert output == "wR . .\n. . wR"


def test_run_ignores_a_leading_or_trailing_space_around_the_board_marker():
    output = run(" Board:\nwK . .\nCommands:\nprint board\n")

    assert output == "wK . ."


def test_main_reads_from_the_input_stream_and_writes_the_result_to_the_output_stream():
    input_stream = io.StringIO("Board:\nwK . .\n. . .\n. . .\nCommands:\nprint board\n")
    output_stream = io.StringIO()

    main(input_stream=input_stream, output_stream=output_stream)

    assert output_stream.getvalue() == "wK . .\n. . .\n. . .\n"
