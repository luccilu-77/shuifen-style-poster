#!/usr/bin/env python3
"""Render typography layout candidates and emit a reviewer manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def render_candidate(renderer: Path, layout: Path, out_dir: Path) -> dict[str, str]:
    data = read_json(layout)
    candidate_id = data.get("candidate_id") or layout.stem
    preview = out_dir / f"{candidate_id}-preview.png"
    text_layer = out_dir / f"{candidate_id}-text-layer.png"
    resolved = out_dir / f"{candidate_id}-resolved-layout.json"
    subprocess.run(
        [
            sys.executable,
            str(renderer),
            "--layout",
            str(layout),
            "--out",
            str(preview),
            "--text-layer",
            str(text_layer),
            "--resolved-layout",
            str(resolved),
        ],
        check=True,
    )
    return {
        "candidate_id": candidate_id,
        "layout_path": str(layout),
        "preview_path": str(preview),
        "text_layer_path": str(text_layer),
        "resolved_layout_path": str(resolved),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--renderer",
        type=Path,
        default=Path(__file__).with_name("typography_renderer.py"),
    )
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    layouts = sorted(args.candidate_dir.glob("*.json"))
    if not layouts:
        raise SystemExit(f"No candidate JSON files found in {args.candidate_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    candidates = [render_candidate(args.renderer, layout, args.out_dir) for layout in layouts]
    manifest = {
        "schema_version": "1.0",
        "reviewer_role": "Typography Visual Reviewer",
        "pass_threshold": 82,
        "max_iterations": 3,
        "score_dimensions": [
            "composition",
            "hierarchy",
            "spacing",
            "rhythm",
            "font_personality",
            "background_integration",
            "readability",
            "commercial_quality",
            "surface_alignment",
            "perspective_accuracy",
            "material_realism",
            "lighting_consistency",
            "occlusion_accuracy",
        ],
        "review_contract": {
            "output_json_only": True,
            "do_not_edit_images": True,
            "do_not_redraw_glyphs": True,
            "corrections_may_only_patch_layout_parameters": True,
        },
        "candidates": candidates,
    }
    manifest_path = args.manifest or (args.out_dir / "reviewer-input-manifest.json")
    write_json(manifest, manifest_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
