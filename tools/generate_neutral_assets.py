#!/usr/bin/env python3
"""Regenerate the neutral 1200×630 social-card placeholder with the standard library."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


WIDTH = 1200
HEIGHT = 630


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _pixel(x: int, y: int) -> tuple[int, int, int]:
    paper = (247, 245, 239)
    ink = (24, 32, 29)
    accent = (36, 95, 120)
    if x < 24:
        return accent
    # A deliberately plain meet/part placeholder; no production mark is traced.
    left = 150 <= x <= 500 and 185 <= y <= 445
    right = 700 <= x <= 1050 and 185 <= y <= 445
    rule = 500 <= x <= 700 and 310 <= y <= 320
    if left or right:
        border = x in {150, 500, 700, 1050} or y in {185, 445}
        return accent if border else (255, 255, 255)
    if rule:
        return ink
    return paper


def build_png() -> bytes:
    rows = []
    for y in range(HEIGHT):
        row = bytearray([0])
        for x in range(WIDTH):
            row.extend(_pixel(x, y))
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    target = Path(__file__).with_name("share-card.png")
    target.write_bytes(build_png())
    print(target)
