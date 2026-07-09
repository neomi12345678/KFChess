from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import parse as parse_board
from kungfu_chess.io.board_printer import print_board
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.texttests.script_parser import (
    AssertPrintBoardInstruction,
    ClickInstruction,
    SetBoardInstruction,
    WaitInstruction,
    parse,
)


class ScriptAssertionError(Exception):
    pass


class ScriptRunner:
    def __init__(self):
        self.board = None
        self.controller = None
        self.game_engine = None

    def run(self, text: str) -> None:
        for instruction in parse(text):
            self._execute(instruction)

    def _execute(self, instruction) -> None:
        if isinstance(instruction, SetBoardInstruction):
            self._set_board("\n".join(instruction.rows))
        elif isinstance(instruction, ClickInstruction):
            self.controller.click(instruction.x, instruction.y)
        elif isinstance(instruction, WaitInstruction):
            self.game_engine.wait(instruction.ms)
        elif isinstance(instruction, AssertPrintBoardInstruction):
            actual = print_board(self.board)
            expected = "\n".join(instruction.expected_rows)
            if actual != expected:
                raise ScriptAssertionError(
                    f"print board mismatch:\nexpected:\n{expected}\nactual:\n{actual}"
                )

    def _set_board(self, text: str) -> None:
        self.board = parse_board(text)
        real_time_arbiter = RealTimeArbiter(self.board)
        self.game_engine = GameEngine(
            board=self.board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter
        )
        board_mapper = BoardMapper(width=self.board.width, height=self.board.height)
        self.controller = Controller(
            board=self.board, board_mapper=board_mapper, game_engine=self.game_engine
        )
