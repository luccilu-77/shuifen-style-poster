#!/usr/bin/env python3
"""Deterministically render local-font typography from layout JSON."""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def rel(value: float, axis: int) -> int:
    return int(round(float(value) * axis))


def color_rgba(color: dict[str, Any], fallback_opacity: float = 1.0) -> tuple[int, int, int, int]:
    hex_value = color.get("hex", "#000000").lstrip("#")
    opacity = float(color.get("opacity", fallback_opacity))
    return (
        int(hex_value[0:2], 16),
        int(hex_value[2:4], 16),
        int(hex_value[4:6], 16),
        max(0, min(255, int(round(opacity * 255)))),
    )


@lru_cache(maxsize=32)
def font_from_path(font_path: str | Path, size: int) -> ImageFont.FreeTypeFont:
    # Memory-backed fonts handle Unicode paths and avoid locking/overwriting
    # a shared temporary font when two families or processes are in use.
    return ImageFont.truetype(BytesIO(Path(font_path).read_bytes()), size)


def measure_text(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    bbox = font.getbbox(text)
    return bbox[0], bbox[1], bbox[2], bbox[3]


def paste_rotated(base: Image.Image, glyph: Image.Image, x: int, y: int, rotation: float) -> None:
    if abs(rotation) > 0.01:
        glyph = glyph.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
    base.alpha_composite(glyph, (x, y))


def glyph_image(
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    scale: float = 1.0,
) -> Image.Image:
    # Render every glyph against the font's shared baseline instead of
    # normalizing each glyph to its own top bounding box. Top-normalization
    # makes punctuation and short horizontal glyphs such as CJK "一" float
    # above the surrounding text.
    ascent, descent = font.getmetrics()
    pad = max(8, int(font.size * 0.18))
    width = max(1, int(math.ceil(font.getlength(text))) + pad * 2)
    height = max(1, ascent + descent + pad * 2)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad, pad + ascent), text, font=font, fill=fill, anchor="ls")
    if abs(scale - 1.0) > 0.001:
        # Uniform scale only. Never stretch x/y independently.
        img = img.resize(
            (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    return img


def flatten_text(text: str, line_breaks: list[str] | None) -> list[str]:
    if line_breaks:
        return list("".join(line_breaks))
    return list(text.replace("\n", ""))


def char_override_map(block: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["index"]): item for item in block.get("chars", [])}


def layout_default_char_positions(block: dict[str, Any], w: int, h: int, base_font: ImageFont.FreeTypeFont) -> list[dict[str, Any]]:
    x0 = rel(block["position"]["x"], w)
    y0 = rel(block["position"]["y"], h)
    letter_spacing = rel(block.get("letter_spacing", 0), w)
    line_spacing = rel(block.get("line_spacing", 0.02), h)
    direction = block.get("direction", "horizontal")
    lines = block.get("line_breaks") or str(block["text"]).splitlines() or [block["text"]]
    align = block.get("align", "left")
    positions: list[dict[str, Any]] = []
    index = 0

    if direction == "vertical":
      cx = x0
      cy = y0
      for line in lines:
          for char in line:
              positions.append({"index": index, "char": char, "x": cx, "y": cy})
              cy += base_font.size + line_spacing
              index += 1
          cx += base_font.size + letter_spacing
          cy = y0
      return positions

    cy = y0
    for line in lines:
        line_width = sum((measure_text(char, base_font)[2] - measure_text(char, base_font)[0]) for char in line)
        line_width += max(0, len(line) - 1) * letter_spacing
        if align == "center":
            cx = x0 - line_width / 2
        elif align == "right":
            cx = x0 - line_width
        else:
            cx = x0
        for char in line:
            positions.append({"index": index, "char": char, "x": cx, "y": cy})
            bbox = measure_text(char, base_font)
            cx += (bbox[2] - bbox[0]) + letter_spacing
            index += 1
        cy += base_font.size + line_spacing
    return positions


def render_block(layer: Image.Image, block: dict[str, Any], canvas: tuple[int, int]) -> None:
    w, h = canvas
    font_size = max(1, rel(float(block["font_size"]), h))
    base_font = font_from_path(block["font_path"], font_size)
    fill = color_rgba(block["color"], float(block.get("opacity", 1)))
    block_rotation = float(block.get("rotation", 0))
    block_scale = float(block.get("scale", 1))
    overrides = char_override_map(block)
    positions = layout_default_char_positions(block, w, h, base_font)

    shadow_cfg = block.get("shadow")
    if shadow_cfg:
        shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        shadow_fill = color_rgba(shadow_cfg.get("color", {"hex": "#000000", "opacity": 0.22}))
        dx = rel(float(shadow_cfg.get("dx", 0)), w)
        dy = rel(float(shadow_cfg.get("dy", 0)), h)
        for item in positions:
            override = overrides.get(item["index"], {})
            x = rel(float(override["x"]), w) if "x" in override else int(item["x"])
            y = rel(float(override["y"]), h) if "y" in override else int(item["y"])
            scale = float(override.get("scale", block_scale))
            rotation = float(override.get("rotation", block_rotation))
            glyph = glyph_image(item["char"], base_font, shadow_fill, scale)
            paste_rotated(shadow_layer, glyph, int(x + dx), int(y + dy), rotation)
        blur_px = max(0, rel(float(shadow_cfg.get("blur", 0)), max(w, h)))
        if blur_px:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_px))
        layer.alpha_composite(shadow_layer)

    for item in positions:
        override = overrides.get(item["index"], {})
        x = rel(float(override["x"]), w) if "x" in override else int(item["x"])
        y = rel(float(override["y"]), h) if "y" in override else int(item["y"])
        scale = float(override.get("scale", block_scale))
        rotation = float(override.get("rotation", block_rotation))
        char_fill = color_rgba(override.get("color", block["color"]), float(block.get("opacity", 1)))
        glyph = glyph_image(item["char"], base_font, char_fill, scale)
        paste_rotated(layer, glyph, x, y, rotation)


def render_layout(layout: dict[str, Any]) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    if layout["constraints"].get("no_glyph_deformation") is not True:
        raise ValueError("Layout must set no_glyph_deformation=true")
    bg_path = Path(layout["assets"]["background_path"])
    background = Image.open(bg_path).convert("RGBA")
    w, h = background.size
    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    for block in layout["text_blocks"]:
        if "scale_x" in block or "scale_y" in block:
            raise ValueError("Non-uniform glyph scaling is forbidden")
        render_block(text_layer, block, (w, h))

    final = Image.alpha_composite(background, text_layer)
    resolved = dict(layout)
    resolved["canvas"] = {"width": w, "height": h, "coordinate_system": "relative-0-1"}
    return final, text_layer, resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--text-layer", type=Path)
    parser.add_argument("--resolved-layout", type=Path)
    args = parser.parse_args()

    layout = load_json(args.layout)
    final, text_layer, resolved = render_layout(layout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    final.convert("RGB").save(args.out, quality=96, subsampling=0)
    if args.text_layer:
        text_layer.save(args.text_layer)
    if args.resolved_layout:
        save_json(resolved, args.resolved_layout)


if __name__ == "__main__":
    main()
