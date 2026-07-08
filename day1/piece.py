EMPTY = "."


def make(color, kind):
    return f"{color}{kind}"


def color(piece):
    return piece[0]


def kind(piece):
    return piece[1]


def is_empty(cell):
    return cell == EMPTY
