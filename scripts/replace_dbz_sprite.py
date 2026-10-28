from __future__ import annotations

from array import array
from io import BytesIO
from pathlib import Path
import re

import requests
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SPRITE_PATH = ROOT / "img" / "dbz_sprite.png"
CSS_PATH = ROOT / "style" / "main.css"
SPRITE_SIZE = (1391, 107)
CELL_SIZE = 107
FIRST_REPLACED_CELL = 11
LAST_REPLACED_CELL = 12

# Images located via web search; these are existing web-hosted images, not generated art.
SOURCES = [
    (
        "Super Saiyan God",
        "https://toppng.com/uploads/preview/oku-super-saiyan-god-red-drawing-dragon-ball-z-goku-god-red-115632257692spat5qbf5.png",
        "https://toppng.com/",
    ),
    (
        "Super Saiyan Blue",
        "https://www.pngfind.com/pngs/m/679-6791466_ssgss-goku-png-dragon-ball-z-png-transparent.png",
        "https://www.pngfind.com/",
    ),
]


def remove_connected_neutral_background(image: Image.Image) -> Image.Image:
    """Remove a light checker/white background only when it touches the canvas edge."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 255:
        return rgba

    width, height = rgba.size
    pixels = rgba.load()
    seen = bytearray(width * height)
    queue = array("I")

    def is_background(index: int) -> bool:
        x, y = index % width, index // width
        r, g, b, a = pixels[x, y]
        return a > 0 and (max(r, g, b) - min(r, g, b) <= 36) and min(r, g, b) >= 170

    def seed(index: int) -> None:
        if not seen[index] and is_background(index):
            seen[index] = 1
            queue.append(index)

    for x in range(width):
        seed(x)
        seed((height - 1) * width + x)
    for y in range(height):
        seed(y * width)
        seed(y * width + width - 1)

    head = 0
    total = width * height
    while head < len(queue):
        index = queue[head]
        head += 1
        x = index % width
        if x > 0:
            n = index - 1
            if not seen[n] and is_background(n):
                seen[n] = 1
                queue.append(n)
        if x + 1 < width:
            n = index + 1
            if not seen[n] and is_background(n):
                seen[n] = 1
                queue.append(n)
        if index >= width:
            n = index - width
            if not seen[n] and is_background(n):
                seen[n] = 1
                queue.append(n)
        if index + width < total:
            n = index + width
            if not seen[n] and is_background(n):
                seen[n] = 1
                queue.append(n)

    if not queue:
        raise RuntimeError("The source image has no detectable transparency and no removable light background.")

    mask = Image.new("L", (width, height), 255)
    mask_pixels = mask.load()
    for index in queue:
        mask_pixels[index % width, index // width] = 0
    rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), mask))
    if rgba.getchannel("A").getbbox() is None:
        raise RuntimeError("Background removal erased the entire character.")
    return rgba


def download_character(name: str, url: str, referer: str) -> Image.Image:
    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; 2048DBZSpriteUpdate/1.0)",
            "Referer": referer,
        },
    )
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert("RGBA")
    image.load()
    image = remove_connected_neutral_background(image)

    bounds = image.getchannel("A").getbbox()
    if not bounds:
        raise RuntimeError(f"{name}: no visible character pixels found.")

    x0, y0, x1, y1 = bounds
    content_width, content_height = x1 - x0, y1 - y0

    # Use a square upper-body crop to match the existing portrait-like game tiles.
    crop_size = min(content_width, int(content_height * 0.82))
    if crop_size < 10:
        raise RuntimeError(f"{name}: source image is unexpectedly small.")
    left = x0 + (content_width - crop_size) // 2
    top = y0
    image = image.crop((left, top, left + crop_size, top + crop_size))

    inner_bounds = image.getchannel("A").getbbox()
    if not inner_bounds:
        raise RuntimeError(f"{name}: the selected crop is empty.")
    image = image.crop(inner_bounds)
    image.thumbnail((101, 101), Image.Resampling.LANCZOS)

    cell = Image.new("RGBA", (CELL_SIZE, CELL_SIZE), (0, 0, 0, 0))
    cell.alpha_composite(
        image,
        ((CELL_SIZE - image.width) // 2, (CELL_SIZE - image.height) // 2),
    )
    if cell.getchannel("A").getbbox() is None:
        raise RuntimeError(f"{name}: rendered tile is empty.")
    return cell


def update_css() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")

    replacements = [
        (
            r"(\.tile\.tile-4096 \.tile-inner \{\s*background-position:\s*)-1284px 0;",
            r"\g<1>-1177px 0;",
        ),
        (
            r"(\.tile\.tile-8192 \.tile-inner \{\s*background-position:\s*)-1177px 0;",
            r"\g<1>-1284px 0;",
        ),
        (
            r"(\.tile\.tile-4096 \.tile-inner \{\s*background-position:\s*)-696px 0;",
            r"\g<1>-638px 0;",
        ),
        (
            r"(\.tile\.tile-8192 \.tile-inner \{\s*background-position:\s*)-638px 0;",
            r"\g<1>-696px 0;",
        ),
    ]

    for pattern, replacement in replacements:
        css, count = re.subn(pattern, replacement, css, count=1)
        if count != 1:
            raise RuntimeError(f"Expected exactly one CSS mapping to update: {pattern}")

    CSS_PATH.write_text(css, encoding="utf-8")


def main() -> None:
    original = Image.open(SPRITE_PATH).convert("RGBA")
    if original.size != SPRITE_SIZE:
        raise RuntimeError(f"Unexpected original sprite dimensions: {original.size}")

    updated = original.copy()
    god = download_character(*SOURCES[0])
    blue = download_character(*SOURCES[1])

    # Remove the two incorrect final images, preserving the first eleven cells.
    clear = Image.new("RGBA", (CELL_SIZE * 2, CELL_SIZE), (0, 0, 0, 0))
    updated.paste(clear, (FIRST_REPLACED_CELL * CELL_SIZE, 0))

    # Keep game progression in order: 4096 = God, 8192 = Blue.
    updated.alpha_composite(god, (FIRST_REPLACED_CELL * CELL_SIZE, 0))
    updated.alpha_composite(blue, (LAST_REPLACED_CELL * CELL_SIZE, 0))

    if updated.size != SPRITE_SIZE:
        raise RuntimeError(f"Output dimensions changed: {updated.size}")
    if ImageChops.difference(
        original.crop((0, 0, FIRST_REPLACED_CELL * CELL_SIZE, CELL_SIZE)),
        updated.crop((0, 0, FIRST_REPLACED_CELL * CELL_SIZE, CELL_SIZE)),
    ).getbbox():
        raise RuntimeError("One or more of the original first eleven cells changed.")
    for index, name in [(FIRST_REPLACED_CELL, "Super Saiyan God"), (LAST_REPLACED_CELL, "Super Saiyan Blue")]:
        cell = updated.crop((index * CELL_SIZE, 0, (index + 1) * CELL_SIZE, CELL_SIZE))
        alpha = cell.getchannel("A")
        if alpha.getbbox() is None or alpha.getextrema()[0] == 255:
            raise RuntimeError(f"{name} tile is empty or its background is not transparent.")

    updated.save(SPRITE_PATH, format="PNG", optimize=True)
    check = Image.open(SPRITE_PATH).convert("RGBA")
    if check.size != (1391, 107):
        raise RuntimeError(f"Saved sprite validation failed: {check.size}")

    update_css()
    print(f"Updated sprite: {check.width}x{check.height}")
    print("Verified: first 11 cells preserved, final cells transparent, 4096=God and 8192=Blue.")


if __name__ == "__main__":
    main()
