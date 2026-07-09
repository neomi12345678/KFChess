from pathlib import Path

import pytest

from texttests.script_runner import ScriptRunner

SCRIPTS_DIR = Path(__file__).parent / "scripts"


@pytest.mark.parametrize("script_path", sorted(SCRIPTS_DIR.glob("*.kfc")), ids=lambda p: p.name)
def test_script(script_path):
    ScriptRunner().run(script_path.read_text())
