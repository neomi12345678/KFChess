from kungfu_chess.app import App


class SpyController:
    def __init__(self):
        self.clicks = []
        self.selected = None

    def click(self, x, y):
        self.clicks.append((x, y))


def test_on_click_routes_to_controller_click():
    controller = SpyController()
    app = App(controller=controller, game_engine=None, renderer=None)

    app.on_click(150, 250)

    assert controller.clicks == [(150, 250)]
