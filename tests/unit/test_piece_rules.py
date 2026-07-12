from boardio.board_parser import parse
from model.position import Position
from rules.piece_rules import BishopRule, KingRule, KnightRule, PawnRule, QueenRule, RookRule


def test_rook_has_correct_legal_destinations_on_an_empty_board():
    board = parse(". . .\n. wR .\n. . .")
    rook = board.get_piece(Position(1, 1))

    destinations = RookRule().legal_destinations(board, rook)

    assert destinations == {
        Position(0, 1), Position(2, 1),
        Position(1, 0), Position(1, 2),
    }


def test_rook_is_blocked_by_a_friendly_piece():
    board = parse(". wP .\n. wR .\n. . .")
    rook = board.get_piece(Position(1, 1))

    destinations = RookRule().legal_destinations(board, rook)

    assert Position(0, 1) not in destinations


def test_rook_includes_an_enemy_blocker_as_a_legal_destination():
    board = parse(". bP .\n. wR .\n. . .")
    rook = board.get_piece(Position(1, 1))

    destinations = RookRule().legal_destinations(board, rook)

    assert Position(0, 1) in destinations


def test_rook_cannot_pass_an_enemy_blocker():
    board = parse(". . .\n. . .\n. bP .\n. wR .\n. . .")
    rook = board.get_piece(Position(3, 1))

    destinations = RookRule().legal_destinations(board, rook)

    assert Position(2, 1) in destinations
    assert Position(1, 1) not in destinations
    assert Position(0, 1) not in destinations


def test_rook_cannot_move_diagonally():
    board = parse(". . .\n. wR .\n. . .")
    rook = board.get_piece(Position(1, 1))

    destinations = RookRule().legal_destinations(board, rook)

    assert Position(0, 0) not in destinations
    assert Position(0, 2) not in destinations
    assert Position(2, 0) not in destinations
    assert Position(2, 2) not in destinations


def test_bishop_has_correct_legal_destinations_on_an_empty_board():
    board = parse(". . . . .\n. . . . .\n. . wB . .\n. . . . .\n. . . . .")
    bishop = board.get_piece(Position(2, 2))

    destinations = BishopRule().legal_destinations(board, bishop)

    assert destinations == {
        Position(0, 0), Position(1, 1), Position(3, 3), Position(4, 4),
        Position(0, 4), Position(1, 3), Position(3, 1), Position(4, 0),
    }


def test_bishop_does_not_move_straight():
    board = parse(". . . . .\n. . . . .\n. . wB . .\n. . . . .\n. . . . .")
    bishop = board.get_piece(Position(2, 2))

    destinations = BishopRule().legal_destinations(board, bishop)

    assert Position(2, 0) not in destinations
    assert Position(0, 2) not in destinations


def test_bishop_is_blocked_by_a_friendly_piece():
    board = parse(". . . . .\n. wP . . .\n. . wB . .\n. . . . .\n. . . . .")
    bishop = board.get_piece(Position(2, 2))

    destinations = BishopRule().legal_destinations(board, bishop)

    assert Position(1, 1) not in destinations
    assert Position(0, 0) not in destinations


def test_bishop_includes_an_enemy_blocker_but_cannot_pass_it():
    board = parse(". . . . .\n. bP . . .\n. . wB . .\n. . . . .\n. . . . .")
    bishop = board.get_piece(Position(2, 2))

    destinations = BishopRule().legal_destinations(board, bishop)

    assert Position(1, 1) in destinations
    assert Position(0, 0) not in destinations


def test_queen_combines_rook_and_bishop_movement():
    board = parse(". . .\n. wQ .\n. . .")
    queen = board.get_piece(Position(1, 1))

    destinations = QueenRule().legal_destinations(board, queen)

    assert destinations == {
        Position(0, 1), Position(2, 1), Position(1, 0), Position(1, 2),
        Position(0, 0), Position(0, 2), Position(2, 0), Position(2, 2),
    }


def test_knight_jumps_in_l_shapes():
    board = parse(". . . . .\n. . . . .\n. . wN . .\n. . . . .\n. . . . .")
    knight = board.get_piece(Position(2, 2))

    destinations = KnightRule().legal_destinations(board, knight)

    assert destinations == {
        Position(0, 1), Position(0, 3), Position(1, 0), Position(1, 4),
        Position(3, 0), Position(3, 4), Position(4, 1), Position(4, 3),
    }


def test_knight_jumps_over_blockers():
    board = parse(". . . . .\n. wP wP . .\n. . wN . .\n. . . . .\n. . . . .")
    knight = board.get_piece(Position(2, 2))

    destinations = KnightRule().legal_destinations(board, knight)

    assert Position(0, 1) in destinations


def test_knight_cannot_land_on_friendly_piece():
    board = parse(". wP . . .\n. . . . .\n. . wN . .\n. . . . .\n. . . . .")
    knight = board.get_piece(Position(2, 2))

    destinations = KnightRule().legal_destinations(board, knight)

    assert Position(0, 1) not in destinations


def test_king_moves_one_cell_in_any_direction():
    board = parse(". . .\n. wK .\n. . .")
    king = board.get_piece(Position(1, 1))

    destinations = KingRule().legal_destinations(board, king)

    assert destinations == {
        Position(0, 0), Position(0, 1), Position(0, 2),
        Position(1, 0), Position(1, 2),
        Position(2, 0), Position(2, 1), Position(2, 2),
    }


def test_king_cannot_move_two_cells():
    board = parse(". . . . .\n. . . . .\n. . wK . .\n. . . . .\n. . . . .")
    king = board.get_piece(Position(2, 2))

    destinations = KingRule().legal_destinations(board, king)

    assert Position(0, 2) not in destinations


def test_white_pawn_moves_one_row_upward():
    board = parse(". . .\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 1) in destinations


def test_black_pawn_moves_one_row_downward():
    board = parse(". . .\n. bP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(2, 1) in destinations


def test_pawn_captures_one_diagonal_step_forward():
    board = parse("bP . bP\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 0) in destinations
    assert Position(0, 2) in destinations


def test_pawn_cannot_capture_forward():
    board = parse(". bP .\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 1) not in destinations


def test_pawn_has_no_initial_two_step_move():
    board = parse(". . .\n. wP .\n. . .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(3, 1) not in destinations


def test_white_pawn_on_start_row_can_move_two_squares():
    board = parse(". . .\n. . .\n. wP .\n. . .")
    pawn = board.get_piece(Position(2, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(1, 1) in destinations
    assert Position(0, 1) in destinations


def test_black_pawn_on_start_row_can_move_two_squares():
    board = parse(". . .\n. bP .\n. . .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(2, 1) in destinations
    assert Position(3, 1) in destinations


def test_pawn_on_start_row_cannot_double_step_through_a_blocker():
    board = parse(". . .\n. bR .\n. wP .\n. . .")
    pawn = board.get_piece(Position(2, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(1, 1) not in destinations
    assert Position(0, 1) not in destinations


def test_pawn_not_on_start_row_cannot_double_step():
    board = parse(". . .\n. . .\n. wP .\n. . .\n. . .")
    pawn = board.get_piece(Position(2, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 1) not in destinations


def test_pawn_capture_check_skips_a_diagonal_that_is_off_the_board():
    board = parse(". bP .\nwP . .\n. . .")
    pawn = board.get_piece(Position(1, 0))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 0) in destinations
    assert Position(0, 1) in destinations


def test_pawn_cannot_move_diagonally_without_a_capture():
    board = parse(". . .\n. wP .\n. . .")
    pawn = board.get_piece(Position(1, 1))

    destinations = PawnRule().legal_destinations(board, pawn)

    assert Position(0, 0) not in destinations
    assert Position(0, 2) not in destinations
