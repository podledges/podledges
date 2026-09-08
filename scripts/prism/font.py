"""Render exact bundled Geist Mono outlines without a runtime font dependency."""
from __future__ import annotations

import json
from functools import lru_cache
from html import escape
from pathlib import Path


@lru_cache(maxsize=1)
def atlas() -> dict:
    return json.loads(Path(__file__).with_name("glyphs.json").read_text())


def decimal(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def text(value, x, y, size, weight=420, fill="#f5f8ff", opacity=1, anchor="start", extra=""):
    value = str(value)
    glyphs = atlas()["weights"][str(weight)]
    try:
        items = [glyphs[c] for c in value]
    except KeyError as error:
        raise ValueError(f"Unsupported profile character {error.args[0]!r}; rebuild the outline atlas") from error
    scale = size / atlas()["units_per_em"]
    width = sum(advance * scale for _, advance in items)
    if anchor == "end":
        x -= width
    elif anchor == "middle":
        x -= width / 2
    shapes = []
    for path, advance in items:
        if path:
            shapes.append(f'<path transform="translate({decimal(x)} {decimal(y)}) scale({decimal(scale)} -{decimal(scale)})" d="{path}"/>')
        x += advance * scale
    return (
        f'<g data-text="{escape(value, quote=True)}" data-font="Geist Mono" data-size="{size}" '
        f'data-weight="{weight}" fill="{fill}" opacity="{opacity}" {extra}>' + "".join(shapes) + "</g>"
    )
