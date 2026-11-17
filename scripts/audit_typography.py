#!/usr/bin/env python3
"""Measure rendered ink bounds, collisions, and blank glyphs for a layout."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from PIL import Image

from typography_renderer import font_from_path, render_block


def intersect(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def audit(layout):
    with Image.open(layout["assets"]["background_path"]) as source:
        w, h = source.size
    pad = max(w, h)
    bounds, errors, warnings = [], [], []
    zone = layout.get("subject_exclusion_zone")
    zone_px = None if not zone else [
        round(zone["x"] * w), round(zone["y"] * h),
        round((zone["x"] + zone["w"]) * w),
        round((zone["y"] + zone["h"]) * h),
    ]
    for block in layout["text_blocks"]:
        shifted = copy.deepcopy(block)
        shifted["position"]["x"] += pad / w
        shifted["position"]["y"] += pad / h
        for char in shifted.get("chars", []):
            if "x" in char:
                char["x"] += pad / w
            if "y" in char:
                char["y"] += pad / h
        layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad))
        render_block(layer, shifted, (w, h))
        bbox = layer.getchannel("A").getbbox()
        if bbox is None:
            errors.append({"type": "empty_block", "id": block["id"]})
            continue
        bbox = [v - pad for v in bbox]
        font_px = max(1, round(block["font_size"] * h))
        font = font_from_path(block["font_path"], font_px)
        blank = sorted({c for c in block["text"]
                        if not c.isspace() and font.getmask(c).getbbox() is None})
        if blank:
            errors.append({"type": "blank_glyph", "id": block["id"], "characters": blank})
        bounds.append({"id": block["id"], "font_px": font_px, "ink_bbox": bbox})
        if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > w or bbox[3] > h:
            errors.append({"type": "canvas_overflow", "id": block["id"]})
        if zone_px and intersect(bbox, zone_px):
            errors.append({"type": "subject_zone_collision", "id": block["id"]})
        if bbox[0] < 0.06 * w or bbox[2] > 0.94 * w:
            warnings.append({"type": "narrow_side_margin", "id": block["id"]})
    for i, first in enumerate(bounds):
        for second in bounds[i + 1:]:
            if intersect(first["ink_bbox"], second["ink_bbox"]):
                errors.append({"type": "text_block_collision",
                               "ids": [first["id"], second["id"]]})
    return {"canvas": [w, h], "status": "fail" if errors else "pass",
            "blocks": bounds, "errors": errors, "warnings": warnings,
            "scope": "Rendered ink boxes and declared exclusion rectangle. Visual grouping still requires inspection; nonempty missing-glyph boxes are not detected."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    report = audit(layout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "errors": report["errors"],
                      "warnings": report["warnings"]}, ensure_ascii=True))
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
