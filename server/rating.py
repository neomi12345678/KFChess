"""ELO rating update - server-only bookkeeping about *who won*, entirely
separate from game logic. Deliberately not in logic_config.py: that file is
scoped to gameplay timing/movement-shape constants game logic itself reads
(see its own docstring) - rating has no bearing on move/jump rules, and
GameEngine never needs to know it exists.
"""

from typing import Tuple

# Standard chess ELO's own conventional step size - how much of the gap
# between expected and actual outcome one game moves a rating.
K_FACTOR = 32


def expected_score(rating: int, opponent_rating: int) -> float:
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 400))


# This variant never draws (the game ends on a direct king capture - see
# rules.rule_engine.KingCaptureWinCondition), so there's always exactly one
# winner and one loser, never a 0.5/0.5 split to account for.
def updated_ratings(winner_rating: int, loser_rating: int) -> Tuple[int, int]:
    winner_expected = expected_score(winner_rating, loser_rating)
    loser_expected = expected_score(loser_rating, winner_rating)

    new_winner_rating = round(winner_rating + K_FACTOR * (1 - winner_expected))
    new_loser_rating = round(loser_rating + K_FACTOR * (0 - loser_expected))

    return new_winner_rating, new_loser_rating
