import pytest

from texttests.script_runner import ScriptAssertionError, ScriptRunner


def test_run_executes_a_full_script_and_matches_the_expected_board():
    script = "Board\nwR . .\n\nclick 50 50\nclick 250 50\nwait 2000\nprint board\n. . wR\n"

    ScriptRunner().run(script)


def test_run_raises_when_the_printed_board_does_not_match():
    script = "Board\nwR . .\n\nprint board\n. wR .\n"

    with pytest.raises(ScriptAssertionError):
        ScriptRunner().run(script)


def test_run_executes_a_jump_command():
    script = "Board\n. wK .\n\njump 150 50\nwait 1000\nprint board\n. wK .\n"

    ScriptRunner().run(script)
