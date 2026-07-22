from __future__ import annotations

from PIL import Image
from PIL import ImageChops, ImageStat


def find_media_box_by_slot(img: Image.Image, slot_index: int) -> tuple[int, int, int, int]:
    # Jianying's media grid is stable enough for the visible top rows. Use this
    # when we know how many media items existed before import.
    col_width = 136
    row_height = 112
    cols = max(1, (min(img.width, 430) - 105) // col_width)
    col = slot_index % cols
    row = slot_index // cols
    left = 120 + col * col_width
    top = 150 + row * row_height
    return (left, top, left + 116, top + 78)


def find_selected_media_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    # Search for the long cyan sides of Jianying's selected thumbnail outline.
    width, height = img.size
    x1, y1 = 105, 145
    x2, y2 = min(680, width), min(575, height)
    pix = img.load()
    columns: dict[int, int] = {}
    rows: dict[int, int] = {}
    for y in range(y1, y2):
        for x in range(x1, x2):
            r, g, b = pix[x, y][:3]
            if r < 100 and g > 110 and b > 115:
                columns[x] = columns.get(x, 0) + 1
                rows[y] = rows.get(y, 0) + 1
    verticals = [x for x, count in columns.items() if count >= 25]
    horizontals = [y for y, count in rows.items() if count >= 50]

    # Rounded selection borders may have only one continuous vertical side.
    # Pair the two long cyan horizontal edges and derive their x extent.
    horizontal_edges: list[tuple[int, int, int]] = []
    for y in horizontals:
        cyan_x = []
        for x in range(x1, x2):
            r, g, b = pix[x, y][:3]
            if r < 100 and g > 110 and b > 115:
                cyan_x.append(x)
        if cyan_x and cyan_x[-1] - cyan_x[0] >= 70:
            horizontal_edges.append((y, cyan_x[0], cyan_x[-1]))
    for top_y, top_left, top_right in horizontal_edges:
        for bottom_y, bottom_left, bottom_right in reversed(horizontal_edges):
            if not 60 <= bottom_y - top_y <= 95:
                continue
            if abs(top_left - bottom_left) <= 8 and abs(top_right - bottom_right) <= 8:
                return (
                    max(x1, min(top_left, bottom_left) - 12),
                    top_y,
                    min(x2, max(top_right, bottom_right) + 4),
                    bottom_y,
                )

    for left in verticals:
        for right in reversed(verticals):
            if not 95 <= right - left <= 135:
                continue
            for top in horizontals:
                for bottom in reversed(horizontals):
                    if 60 <= bottom - top <= 95:
                        return (left, top, right, bottom)
    return None


def find_selected_media_center(img: Image.Image) -> tuple[int, int] | None:
    box = find_selected_media_box(img)
    if box is None:
        return None
    left, top, right, bottom = box
    return (int((left + right) / 2), int((top + bottom) / 2))


def _visible_media_slots(img: Image.Image) -> list[tuple[int, int, int, int]]:
    slots = []
    panel_right = min(680, img.width)
    columns = max(2, min(4, (panel_right - 105) // 136))
    visible_rows = max(3, min(4, (min(img.height, 590) - 145) // 105))
    for row in range(visible_rows):
        for col in range(columns):
            left = 102 + col * 136
            top = 145 + row * 112
            box = (left, top, left + 134, top + 100)
            if box[2] <= panel_right and box[3] <= min(img.height, 590):
                slots.append(box)
    return slots


def find_new_media_box(before: Image.Image, after: Image.Image) -> tuple[int, int, int, int] | None:
    """Find the imported tile from the visual change, not Jianying's stale selection."""
    if before.size != after.size:
        return None
    scored: list[tuple[float, tuple[int, int, int, int]]] = []
    for box in _visible_media_slots(after):
        diff = ImageChops.difference(before.crop(box).convert("RGB"), after.crop(box).convert("RGB"))
        stat = ImageStat.Stat(diff)
        score = sum(stat.mean) / 3
        scored.append((score, box))
    if not scored:
        return None
    score, box = max(scored, key=lambda item: item[0])
    if score < 4.0:
        return None
    # The thumbnail itself occupies the inner 116x78 area. Returning that box
    # keeps the add-button calculation independent of selection outlines.
    return (box[0] + 18, box[1] + 5, box[0] + 134, box[1] + 83)


def find_video_track_bands(img: Image.Image) -> list[tuple[int, int]]:
    """Return visible full-height track rows from their stable lock controls."""
    _, height = img.size
    y1, y2 = int(height * 0.61), height - 18
    pix = img.convert("RGB").load()
    active: list[int] = []
    for y in range(y1, y2):
        count = 0
        for x in range(40, min(56, img.width)):
            r, g, b = pix[x, y]
            neutral_bright = min(r, g, b) > 105 and max(r, g, b) - min(r, g, b) < 40
            locked_cyan = r < 90 and g > 105 and b > 115
            if neutral_bright or locked_cyan:
                count += 1
        if count >= 2:
            active.append(y)

    centers: list[int] = []
    if active:
        start = previous = active[0]
        for y in active[1:]:
            if y > previous + 3:
                centers.append((start + previous) // 2)
                start = y
            previous = y
        centers.append((start + previous) // 2)

    bands: list[tuple[int, int]] = []
    for index, center in enumerate(centers):
        previous_gap = center - centers[index - 1] if index else None
        next_gap = centers[index + 1] - center if index + 1 < len(centers) else None
        gaps = [gap for gap in (previous_gap, next_gap) if gap is not None]
        estimated_height = min(gaps) if gaps else 58
        half = min(31, max(8, estimated_height // 2 - 2))
        bands.append((center - half, center + half))
    return bands


def track_is_locked(img: Image.Image, band: tuple[int, int]) -> bool:
    pix = img.convert("RGB").load()
    center = (band[0] + band[1]) // 2
    for y in range(max(0, center - 10), min(img.height, center + 11)):
        for x in range(38, min(58, img.width)):
            r, g, b = pix[x, y]
            if r < 85 and g > 105 and b > 115:
                return True
    return False


def track_has_clip_at(img: Image.Image, x: int, band: tuple[int, int]) -> bool:
    pix = img.convert("RGB").load()
    hits = 0
    total = 0
    for y in range(max(0, band[0] + 3), min(img.height, band[1] - 2), 2):
        for px in range(max(85, x + 4), min(img.width - 5, x + 42), 3):
            r, g, b = pix[px, y]
            total += 1
            if max(r, g, b) > 72 or max(r, g, b) - min(r, g, b) > 18:
                hits += 1
    return total > 0 and hits / total > 0.22


def find_rightmost_clip_center(img: Image.Image, band: tuple[int, int]) -> int | None:
    pix = img.convert("RGB").load()
    active_columns: list[int] = []
    for x in range(135, img.width - 25):
        hits = 0
        total = 0
        for y in range(max(0, band[0] + 4), min(img.height, band[1] - 3), 3):
            r, g, b = pix[x, y]
            total += 1
            if max(r, g, b) > 68 or max(r, g, b) - min(r, g, b) > 16:
                hits += 1
        if total and hits / total > 0.28:
            active_columns.append(x)

    runs: list[tuple[int, int]] = []
    if active_columns:
        start = previous = active_columns[0]
        for x in active_columns[1:]:
            if x > previous + 2:
                if previous - start >= 18:
                    runs.append((start, previous))
                start = x
            previous = x
        if previous - start >= 18:
            runs.append((start, previous))
    if not runs:
        return None
    left, right = runs[-1]
    return (left + right) // 2


def find_selected_timeline_clip(
    img: Image.Image, bands: list[tuple[int, int]]
) -> tuple[int, int] | None:
    """Return the center of Jianying's white-selected timeline clip."""
    if not bands:
        return None
    pix = img.convert("RGB").load()
    edges: list[tuple[int, int, int]] = []
    y_start = max(int(img.height * 0.61), bands[0][0] - 18)
    y_end = min(img.height - 8, bands[-1][1] + 18)
    for y in range(y_start, y_end + 1):
        bright = []
        for x in range(130, img.width - 20):
            r, g, b = pix[x, y]
            if min(r, g, b) > 175 and max(r, g, b) - min(r, g, b) < 30:
                bright.append(x)
        if not bright:
            continue
        start = previous = bright[0]
        runs = []
        for x in bright[1:]:
            if x > previous + 2:
                runs.append((start, previous))
                start = x
            previous = x
        runs.append((start, previous))
        left, right = max(runs, key=lambda run: run[1] - run[0])
        if right - left >= 28:
            edges.append((y, left, right))

    best: tuple[int, int, int] | None = None
    for top_y, top_left, top_right in edges:
        for bottom_y, bottom_left, bottom_right in reversed(edges):
            height = bottom_y - top_y
            if not 20 <= height <= 100:
                continue
            if abs(top_left - bottom_left) > 6 or abs(top_right - bottom_right) > 6:
                continue
            width = min(top_right, bottom_right) - max(top_left, bottom_left)
            if best is None or width > best[0]:
                best = (
                    width,
                    (top_left + top_right + bottom_left + bottom_right) // 4,
                    (top_y + bottom_y) // 2,
                )
    return None if best is None else (best[1], best[2])


def find_playhead_x(img: Image.Image) -> int | None:
    # Require Jianying's ruler handle and a genuinely continuous vertical line.
    # Bright overlays can otherwise outscore the playhead near the right edge.
    width, height = img.size
    x_start = 70
    x_end = width - 20
    marker_start = int(height * 0.56)
    marker_end = int(height * 0.63)
    y_start = int(height * 0.57)
    y_end = height - 35
    pix = img.load()
    best_x = None
    best_score = 0
    for x in range(x_start, x_end):
        marker = 0
        for y in range(marker_start, marker_end):
            r, g, b = pix[x, y][:3]
            if min(r, g, b) > 175 and max(r, g, b) - min(r, g, b) < 24:
                marker += 1
        if marker < 2:
            continue
        line_rows: list[int] = []
        for y in range(y_start, y_end):
            r, g, b = pix[x, y][:3]
            if (
                110 <= r <= 215
                and 110 <= g <= 215
                and 110 <= b <= 215
                and max(r, g, b) - min(r, g, b) < 35
            ):
                line_rows.append(y)
        longest_run = 0
        if line_rows:
            start = previous = line_rows[0]
            for y in line_rows[1:]:
                if y > previous + 1:
                    longest_run = max(longest_run, previous - start + 1)
                    start = y
                previous = y
            longest_run = max(longest_run, previous - start + 1)
        if longest_run < 45:
            continue
        score = marker * 8 + longest_run
        if score > best_score:
            best_score = score
            best_x = x
    return best_x if best_score >= 61 else None


def timeline_drop_y(img: Image.Image) -> int:
    return int(img.height * 0.81)
