# Test suite: https://github.com/neomi12345678/KFChess

from game import run


if __name__ == "__main__":  # pragma: no cover
    import sys

    lines = [line.strip() for line in sys.stdin.read().splitlines()]
    run(lines)
