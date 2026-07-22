from PIL import Image, ImageDraw

from jy_live_paste.vision import (
    find_selected_timeline_clip,
    find_new_media_box,
    find_playhead_x,
    find_rightmost_clip_center,
    find_selected_media_center,
    find_video_track_bands,
    track_has_clip_at,
)


def test_find_selected_media_center() -> None:
    img = Image.new("RGB", (500, 500), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    draw.rectangle((120, 150, 240, 230), outline=(0, 210, 220), width=3)
    center = find_selected_media_center(img)
    assert center is not None
    assert 175 <= center[0] <= 185
    assert 185 <= center[1] <= 195


def test_track_has_clip_at() -> None:
    img = Image.new("RGB", (1280, 720), (25, 25, 25))
    draw = ImageDraw.Draw(img)
    draw.rectangle((600, 560, 760, 620), fill=(20, 105, 115))
    assert track_has_clip_at(img, 610, (555, 625))
    assert not track_has_clip_at(img, 900, (555, 625))


def test_find_rightmost_clip_center_ignores_playhead_line() -> None:
    img = Image.new("RGB", (1280, 720), (25, 25, 25))
    draw = ImageDraw.Draw(img)
    draw.rectangle((200, 560, 400, 620), fill=(20, 105, 115))
    draw.rectangle((650, 560, 820, 620), fill=(25, 95, 105))
    draw.line((1000, 550, 1000, 680), fill=(170, 170, 170), width=2)
    center = find_rightmost_clip_center(img, (555, 625))
    assert center is not None
    assert 725 <= center <= 745


def test_find_selected_timeline_clip_from_white_border() -> None:
    img = Image.new("RGB", (1280, 720), (25, 25, 25))
    draw = ImageDraw.Draw(img)
    bands = [(520, 570), (580, 630)]
    draw.rectangle((700, 582, 940, 628), outline=(230, 230, 230), width=2)
    assert find_selected_timeline_clip(img, bands) == (820, 605)


def test_find_playhead_x() -> None:
    img = Image.new("RGB", (1280, 720), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.line((333, 440, 333, 690), fill=(150, 150, 150), width=2)
    draw.rectangle((329, 432, 337, 445), fill=(220, 220, 220))
    assert find_playhead_x(img) in {333, 334}


def test_find_playhead_rejects_aligned_clip_edge() -> None:
    img = Image.new("RGB", (1280, 720), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.line((500, 470, 500, 690), fill=(160, 160, 160), width=2)
    draw.line((900, 440, 900, 690), fill=(150, 150, 150), width=2)
    draw.rectangle((896, 432, 904, 445), fill=(220, 220, 220))
    assert find_playhead_x(img) in {900, 901}


def test_find_playhead_rejects_bright_overlay_near_right_edge() -> None:
    img = Image.new("RGB", (1920, 1080), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.line((190, 660, 190, 1015), fill=(150, 150, 150), width=2)
    draw.rectangle((186, 648, 194, 662), fill=(220, 220, 220))
    draw.rectangle((1680, 650, 1790, 740), fill=(220, 220, 220))
    draw.rectangle((1737, 905, 1743, 910), fill=(180, 180, 180))
    assert find_playhead_x(img) in {190, 191}


def test_find_new_media_box_ignores_old_selected_tile() -> None:
    before = Image.new("RGB", (500, 500), (25, 25, 25))
    after = before.copy()
    draw = ImageDraw.Draw(after)
    draw.rectangle((120, 150, 236, 228), outline=(0, 210, 220), width=3)
    draw.rectangle((120, 262, 236, 340), fill=(180, 80, 40))
    assert find_new_media_box(before, after) == (120, 262, 236, 340)


def test_find_new_media_box_supports_fourth_visible_row() -> None:
    before = Image.new("RGB", (1280, 720), (25, 25, 25))
    after = before.copy()
    draw = ImageDraw.Draw(after)
    draw.rectangle((120, 486, 236, 564), fill=(40, 150, 190))
    assert find_new_media_box(before, after) == (120, 486, 236, 564)


def test_find_video_track_bands_uses_track_lock_centers() -> None:
    img = Image.new("RGB", (1280, 720), (25, 25, 25))
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 450, 400, 470), fill=(110, 80, 140))
    draw.rectangle((100, 490, 700, 535), fill=(50, 105, 120))
    draw.rectangle((100, 550, 900, 610), fill=(90, 100, 110))
    draw.rectangle((44, 456, 49, 462), fill=(180, 180, 180))
    draw.rectangle((44, 509, 49, 515), fill=(180, 180, 180))
    draw.rectangle((44, 577, 49, 583), fill=(180, 180, 180))
    bands = find_video_track_bands(img)
    assert len(bands) == 3
    assert [sum(band) // 2 for band in bands] == [459, 512, 580]
