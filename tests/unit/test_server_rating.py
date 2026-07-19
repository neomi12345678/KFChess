from server.rating import K_FACTOR, expected_score, updated_ratings


def test_expected_score_is_half_for_equal_ratings():
    assert expected_score(1200, 1200) == 0.5


def test_expected_score_favors_the_higher_rated_player():
    assert expected_score(1400, 1200) > 0.5
    assert expected_score(1200, 1400) < 0.5


def test_updated_ratings_splits_the_full_k_factor_between_equal_players():
    # Equal ratings: each was "expected" to score 0.5, so an upset (there's
    # no draw in this variant - see rules.rule_engine.KingCaptureWinCondition)
    # moves each rating by the full K_FACTOR/2.
    new_winner, new_loser = updated_ratings(1200, 1200)

    assert new_winner == 1200 + K_FACTOR // 2
    assert new_loser == 1200 - K_FACTOR // 2


def test_updated_ratings_moves_the_underdog_winner_more():
    # A lower-rated player winning was less expected, so their rating moves
    # by more than K_FACTOR/2, and the higher-rated loser's drops by more.
    new_winner, new_loser = updated_ratings(winner_rating=1200, loser_rating=1400)

    assert new_winner - 1200 > K_FACTOR // 2
    assert 1400 - new_loser > K_FACTOR // 2


def test_updated_ratings_moves_the_favorite_winner_less():
    new_winner, new_loser = updated_ratings(winner_rating=1400, loser_rating=1200)

    assert new_winner - 1400 < K_FACTOR // 2
    assert 1200 - new_loser < K_FACTOR // 2
