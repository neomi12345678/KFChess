from boardio.board_parser import parse
from model.piece import PAWN, QUEEN, ROOK
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.promotion_rule import LastRankPromotion


def test_last_rank_promotion_promotes_a_white_pawn_at_row_zero():
    board = parse(". . .\n. wP .")
    pawn = board.get_piece(Position(1, 1))
    pawn.cell = Position(0, 1)

    LastRankPromotion().promote(pawn, board.height)

    assert pawn.kind == QUEEN


def test_last_rank_promotion_leaves_a_pawn_alone_before_the_last_rank():
    board = parse(". . .\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    LastRankPromotion().promote(pawn, board.height)

    assert pawn.kind == PAWN


def test_last_rank_promotion_ignores_non_pawns():
    board = parse("wR . .")
    rook = board.get_piece(Position(0, 0))

    LastRankPromotion().promote(rook, board.height)

    assert rook.kind == ROOK


def test_last_rank_promotion_promotion_target_is_configurable():
    board = parse(". . .\n. wP .")
    pawn = board.get_piece(Position(1, 1))
    pawn.cell = Position(0, 1)

    LastRankPromotion(promote_to=ROOK).promote(pawn, board.height)

    assert pawn.kind == ROOK


class NoPromotion:
    def promote(self, piece, board_height):
        pass


def test_real_time_arbiter_accepts_a_custom_promotion_rule():
    board = parse(". . .\n. wP .")
    arbiter = RealTimeArbiter(board, promotion_rule=NoPromotion())
    pawn = board.get_piece(Position(1, 1))

    arbiter.start_motion(pawn, Position(1, 1), Position(0, 1))
    arbiter.advance_time(1000)

    assert board.get_piece(Position(0, 1)).kind == PAWN
