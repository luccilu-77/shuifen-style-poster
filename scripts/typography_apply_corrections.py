#!/usr/bin/env python3
"""Apply reviewer corrections to a typography layout JSON."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def decode_pointer(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with /: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def get_parent(root: Any, pointer: str) -> tuple[Any, str]:
    parts = decode_pointer(pointer)
    if not parts:
        raise ValueError("Cannot patch document root")
    current = root
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current, parts[-1]


def apply_op(root: Any, op: dict[str, Any]) -> None:
    operation = op["op"]
    parent, key = get_parent(root, op["path"])
    if isinstance(parent, list):
        index = len(parent) if key == "-" else int(key)
        if operation == "add":
            parent.insert(index, op["value"])
        elif operation == "replace":
            parent[index] = op["value"]
        elif operation == "remove":
            del parent[index]
        else:
            raise ValueError(f"Unsupported patch operation: {operation}")
    else:
        if operation in {"add", "replace"}:
            parent[key] = op["value"]
        elif operation == "remove":
            del parent[key]
        else:
            raise ValueError(f"Unsupported patch operation: {operation}")


def forbid_dangerous_patch(op: dict[str, Any]) -> None:
    path = op.get("path", "")
    forbidden_roots = (
        "/assets/background_path",
        "/assets/font_path",
        "/assets/surface_analysis_path",
        "/intent/primary_copy",
        "/intent/secondary_copy",
        "/constraints/local_font_only",
        "/constraints/no_ai_redraw",
        "/constraints/no_glyph_deformation",
    )
    if path.startswith(forbidden_roots):
        raise ValueError(f"Reviewer corrections cannot modify protected field: {path}")
    if path.endswith("/scale_x") or path.endswith("/scale_y"):
        raise ValueError("Non-uniform glyph scaling is forbidden")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--corrections", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    layout = read_json(args.layout)
    review = read_json(args.corrections)
    updated = copy.deepcopy(layout)
    patch = review.get("corrections", {}).get("patch", [])
    for op in patch:
        forbid_dangerous_patch(op)
        apply_op(updated, op)
    updated["iteration"] = int(updated.get("iteration", 0)) + 1
    write_json(updated, args.out)
    print(args.out)


if __name__ == "__main__":
    main()
