import numpy as np
import pytest

from view.canvas.img import Img
from piece_config import ASSETS_DIR

BOARD_PATH = ASSETS_DIR / "board.png"


def make_img(height, width, channels):
    img = Img()
    img.img = np.zeros((height, width, channels), dtype=np.uint8)
    return img


def test_read_loads_a_real_image_file_from_disk():
    img = Img().read(BOARD_PATH)

    assert img.img is not None


def test_read_raises_file_not_found_for_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        Img().read(tmp_path / "does_not_exist.png")


def test_read_without_keep_aspect_resizes_to_the_exact_target_size():
    img = Img().read(BOARD_PATH, size=(50, 60))

    height, width = img.img.shape[:2]
    assert (width, height) == (50, 60)


def test_read_with_keep_aspect_shrinks_the_longer_side_to_fit_without_cropping():
    img = Img().read(BOARD_PATH, size=(100, 100), keep_aspect=True)

    height, width = img.img.shape[:2]
    assert max(height, width) == 100


def test_draw_on_raises_if_the_source_image_is_not_loaded():
    target = make_img(10, 10, 4)

    with pytest.raises(ValueError):
        Img().draw_on(target, 0, 0)


def test_draw_on_raises_if_the_target_image_is_not_loaded():
    source = make_img(4, 4, 4)

    with pytest.raises(ValueError):
        source.draw_on(Img(), 0, 0)


def test_draw_on_converts_a_3_channel_source_to_match_a_4_channel_target():
    source = make_img(4, 4, 3)
    target = make_img(10, 10, 4)

    source.draw_on(target, 2, 2)

    assert source.img.shape[2] == 4


def test_draw_on_converts_a_4_channel_source_to_match_a_3_channel_target():
    source = make_img(4, 4, 4)
    source.img[:, :, 3] = 255
    target = make_img(10, 10, 3)

    source.draw_on(target, 2, 2)

    assert source.img.shape[2] == 3


def test_draw_on_raises_if_the_source_does_not_fit_at_the_given_position():
    source = make_img(4, 4, 4)
    target = make_img(5, 5, 4)

    with pytest.raises(ValueError):
        source.draw_on(target, 3, 3)


def test_draw_on_blends_a_4_channel_source_by_its_alpha_channel():
    source = make_img(2, 2, 4)
    source.img[:, :] = (10, 20, 30, 255)  # fully opaque
    target = make_img(4, 4, 4)
    target.img[:, :] = (0, 0, 0, 255)

    source.draw_on(target, 1, 1)

    assert np.array_equal(target.img[1:3, 1:3, :3], source.img[:, :, :3])


def test_draw_on_copies_a_same_channel_count_source_directly_without_blending():
    source = make_img(2, 2, 3)
    source.img[:, :] = (10, 20, 30)
    target = make_img(4, 4, 3)

    source.draw_on(target, 1, 1)

    assert np.array_equal(target.img[1:3, 1:3], source.img)


def test_put_text_raises_if_the_image_is_not_loaded():
    with pytest.raises(ValueError):
        Img().put_text("hi", 0, 0, font_size=1.0)


def test_put_text_draws_onto_a_loaded_image():
    img = make_img(20, 100, 4)
    before = img.img.copy()

    img.put_text("hi", 0, 15, font_size=1.0)

    assert not np.array_equal(img.img, before)
