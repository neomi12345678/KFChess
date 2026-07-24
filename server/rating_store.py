"""ELO rating persistence, read/written against the same shared accounts
table server/accounts.py's UserStore authenticates against (see
server/accounts_db.py's own docstring on why they share one connection).
The rating *math* itself lives separately, in server/rating.py's
updated_ratings - this class only ever gets/sets the number a username
currently has, never computes a new one; server/session.py's
finalize_ratings_if_game_over is what combines the two.

Every row this ever reads/writes was already created by UserStore.login's
own INSERT (at STARTING_RATING) - rating_for/update_rating both assume the
username has logged in at least once already, the same assumption
server/session.py's GameSession already makes (it's only ever constructed
for two usernames matchmaking or a room already paired, both already
logged in).
"""

from server.accounts_db import AccountsDatabase


class RatingStore:
    def __init__(self, database: AccountsDatabase):
        self._database = database

    def rating_for(self, username: str) -> int:
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT rating FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            return row[0]

    def update_rating(self, username: str, rating: int) -> None:
        with self._database.lock:
            self._database.connection.execute(
                "UPDATE accounts SET rating = ? WHERE username = ?", (rating, username)
            )
            self._database.connection.commit()
