"""The site's social card image: one PNG, drawn from the masthead mark.

Why a PNG at all: no social platform renders an SVG as a card image, so the per-angle
SVG cards publications used to ship (retired; bundles up to ``publish-0.7.0``
still hold them) were invisible everywhere they were meant to be seen.

Why *this* PNG — one flat brand image rather than a raster of each angle card — is a
determinism decision, not a design preference.  A candidate bundle is re-derived byte for
byte by ``verify_candidate``, and the whole production tree by ``verify_site``.  Text
rasterization is not byte-stable across hosts (FreeType/HarfBuzz versions move), so a
rasterized angle card inside either of those paths would turn a library upgrade into a
failed verification of already-approved publications.  Everything drawn here is flat
geometry with no glyphs, and the shipped bytes are checked in beside this module, so the
asset is a constant either way.  The per-angle facts still reach every platform: the card
text is ``og:title`` / ``og:description``, which the share landing pages state per angle.

The mark is the masthead's: two rounded columns, A in blue and B in amber, on paper.
Regenerate the checked-in bytes with ``python -m newsab_publish.social_card``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


#: Served by the chrome layer, so the card is a site release fact like the stylesheet:
#: changing it never touches an approved content document.
ASSET_PATH = "assets/share-card.png"
ASSET_URL = f"/{ASSET_PATH}"
WIDTH = 1200
HEIGHT = 630

_PAPER = (0xFB, 0xFA, 0xF7)
_COLUMN_A = (0x1D, 0x4E, 0x6B)
_COLUMN_B = (0x8A, 0x5A, 0x16)
_RULE = (0xD9, 0xD8, 0xD0)

#: The favicon's 32-unit grid — ``rect(3,6,11,20) rx=2`` twice — scaled and centred.
_GRID = 15
_MARK_LEFT = (WIDTH - 26 * _GRID) // 2 - 3 * _GRID
_MARK_TOP = (HEIGHT - 20 * _GRID) // 2 - 6 * _GRID - 22


def _blend(canvas: bytearray, x: int, y: int, colour: tuple[int, int, int], alpha: float) -> None:
    if alpha <= 0.0:
        return
    offset = (y * WIDTH + x) * 3
    if alpha >= 1.0:
        canvas[offset : offset + 3] = bytes(colour)
        return
    for channel in range(3):
        under = canvas[offset + channel]
        value = under + (colour[channel] - under) * alpha
        canvas[offset + channel] = int(value + 0.5)


def _add_span(coverage: list[float], left: float, right: float, weight: float) -> None:
    """Accumulate one horizontal span's coverage, antialiasing only its two edges."""
    if right <= left:
        return
    left = max(left, 0.0)
    right = min(right, float(WIDTH))
    if right <= left:
        return
    first = int(left)
    last = int(right - 1e-9)
    if first == last:
        coverage[first] += (right - left) * weight
        return
    coverage[first] += (first + 1 - left) * weight
    for x in range(first + 1, last):
        coverage[x] += weight
    coverage[last] += (right - last) * weight


def _rounded_rect(
    canvas: bytearray,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
    colour: tuple[int, int, int],
) -> None:
    """Fill one rounded rectangle with four-times vertical supersampling.

    Pure float arithmetic on the same inputs gives the same pixels on every host, which
    is the only property this drawing code has to guarantee.
    """
    samples = 4
    weight = 1.0 / samples
    radius = min(radius, width / 2, height / 2)
    top = max(int(y), 0)
    bottom = min(int(y + height + 1.0), HEIGHT)
    for row in range(top, bottom):
        coverage = [0.0] * WIDTH
        for sample in range(samples):
            centre = row + (sample + 0.5) * weight
            if centre < y or centre > y + height:
                continue
            inset = 0.0
            if centre < y + radius:
                offset = radius - (centre - y)
                inset = radius - (radius * radius - offset * offset) ** 0.5
            elif centre > y + height - radius:
                offset = radius - (y + height - centre)
                inset = radius - (radius * radius - offset * offset) ** 0.5
            _add_span(coverage, x + inset, x + width - inset, weight)
        for column, alpha in enumerate(coverage):
            if alpha > 0.0:
                _blend(canvas, column, row, colour, min(alpha, 1.0))


def render_pixels() -> bytearray:
    """The card as raw RGB bytes, top row first."""
    canvas = bytearray(bytes(_PAPER) * (WIDTH * HEIGHT))
    for grid_x, colour in ((3, _COLUMN_A), (18, _COLUMN_B)):
        _rounded_rect(
            canvas,
            _MARK_LEFT + grid_x * _GRID,
            _MARK_TOP + 6 * _GRID,
            11 * _GRID,
            20 * _GRID,
            2 * _GRID,
            colour,
        )
    # The masthead's rule under the wordmark, kept at the same width as the mark.
    _rounded_rect(canvas, float(_MARK_LEFT + 3 * _GRID), float(_MARK_TOP + 30 * _GRID),
                  float(26 * _GRID), 3.0, 1.5, _RULE)
    return canvas


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png(pixels: bytes) -> bytes:
    """Encode RGB8 with the Up filter, which turns the card's flat rows into zeros."""
    stride = WIDTH * 3
    raw = bytearray()
    previous = bytes(stride)
    for row in range(HEIGHT):
        line = pixels[row * stride : (row + 1) * stride]
        raw.append(2)
        raw.extend((line[index] - previous[index]) & 0xFF for index in range(stride))
        previous = line
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def decode_png(payload: bytes) -> tuple[int, int, bytes]:
    """Decode our own RGB8 output back to pixels — deterministic on every host.

    Compression is not byte-stable across zlib builds, so the checked-in asset is
    compared to a fresh render through this, not through re-encoding.
    """
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    offset = 8
    width = height = 0
    data = bytearray()
    while offset < len(payload):
        (length,) = struct.unpack(">I", payload[offset : offset + 4])
        kind = payload[offset + 4 : offset + 8]
        body = payload[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, *_ = struct.unpack(">IIBBBBB", body)
            if (depth, colour) != (8, 2):
                raise ValueError("unsupported PNG colour type")
        elif kind == b"IDAT":
            data.extend(body)
        elif kind == b"IEND":
            break
    stride = width * 3
    raw = zlib.decompress(bytes(data))
    pixels = bytearray()
    previous = bytes(stride)
    for row in range(height):
        start = row * (stride + 1)
        filter_type = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        if filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"unsupported PNG filter: {filter_type}")
        pixels.extend(line)
        previous = bytes(line)
    return width, height, bytes(pixels)


def asset_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "share-card.png"


def card_bytes() -> bytes:
    """The checked-in card bytes — a constant, so every build ships the same asset."""
    return asset_path().read_bytes()


def main() -> None:
    target = asset_path()
    target.write_bytes(encode_png(bytes(render_pixels())))
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
