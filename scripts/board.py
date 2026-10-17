#!/usr/bin/env python3
"""Create and render a self-contained prototype selection board."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_DIR / "assets" / "dashboard-template.html"
ID_PATTERN = re.compile(r"P-\d{3,}$")
REQUIRED_TEXT = (
    "title", "direction", "summary", "layout", "palette",
    "interaction", "responsive", "rationale", "file",
)


def fail(message: str) -> None:
    raise ValueError(message)


def safe_file(project_dir: Path, value: str, suffix: str) -> None:
    if not isinstance(value, str) or not value:
        fail(f"invalid path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != suffix:
        fail(f"path must be a project-relative {suffix} file: {value}")
    target = (project_dir / relative).resolve()
    if not target.is_relative_to(project_dir.resolve()) or not target.is_file():
        fail(f"missing or unsafe file: {value}")


def validate(project_dir: Path, data: dict) -> None:
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        fail("manifest.json requires schemaVersion: 1")
    project = data.get("project")
    if not isinstance(project, dict) or not all(isinstance(project.get(key), str) and project[key].strip() for key in ("title", "brief")):
        fail("project.title and project.brief are required")
    batches = data.get("batches")
    prototypes = data.get("prototypes")
    if not isinstance(batches, list) or not isinstance(prototypes, list):
        fail("batches and prototypes must be arrays")
    if not batches and prototypes:
        fail("prototypes require a batch")

    known_ids: set[str] = set()
    batch_ids: set[str] = set()
    numbers: list[int] = []
    for batch in batches:
        if not isinstance(batch, dict):
            fail("each batch must be an object")
        number = batch.get("number")
        if type(number) is not int or number < 1 or number in numbers:
            fail(f"batch number must be a unique positive integer: {number}")
        numbers.append(number)
        if not all(isinstance(batch.get(key), str) and batch[key].strip() for key in ("title", "brief")):
            fail(f"batch {number} requires title and brief")
        ids = batch.get("ids")
        parents = batch.get("parentIds", [])
        if not isinstance(ids, list) or len(ids) != 6 or len(set(ids)) != 6:
            fail(f"batch {number} must list exactly six unique ids")
        if not isinstance(parents, list) or any(parent not in known_ids for parent in parents):
            fail(f"batch {number} has unknown or future parentIds")
        for proto_id in ids:
            if not isinstance(proto_id, str) or not ID_PATTERN.fullmatch(proto_id) or proto_id in batch_ids:
                fail(f"invalid or duplicate prototype id: {proto_id}")
            batch_ids.add(proto_id)
        known_ids.update(ids)
    if numbers != sorted(numbers):
        fail("batches must be ordered by number")

    seen: set[str] = set()
    seen_files: set[str] = set()
    by_batch = {batch["number"]: set(batch["ids"]) for batch in batches}
    id_to_batch = {proto_id: batch["number"] for batch in batches for proto_id in batch["ids"]}
    for item in prototypes:
        if not isinstance(item, dict):
            fail("each prototype must be an object")
        proto_id = item.get("id")
        if proto_id not in batch_ids or proto_id in seen:
            fail(f"unknown or duplicate prototype entry: {proto_id}")
        seen.add(proto_id)
        if item.get("batch") not in by_batch or proto_id not in by_batch[item["batch"]]:
            fail(f"prototype {proto_id} has wrong batch")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in REQUIRED_TEXT):
            fail(f"prototype {proto_id} has missing design metadata")
        if not isinstance(item.get("tags"), list) or any(not isinstance(tag, str) for tag in item["tags"]):
            fail(f"prototype {proto_id} requires string tags")
        parents = item.get("parentIds")
        if not isinstance(parents, list) or any(parent not in batch_ids for parent in parents):
            fail(f"prototype {proto_id} has invalid parentIds")
        if any(id_to_batch[parent] >= item["batch"] for parent in parents):
            fail(f"prototype {proto_id} can only reference earlier batches")
        if item["file"] in seen_files:
            fail(f"multiple prototypes use the same file: {item['file']}")
        seen_files.add(item["file"])
        safe_file(project_dir, item["file"], ".html")
        if item.get("preview"):
            safe_file(project_dir, item["preview"], ".png")
    if seen != batch_ids:
        fail(f"missing prototype entries: {', '.join(sorted(batch_ids - seen))}")
    ordered_ids = [proto_id for batch in batches for proto_id in batch["ids"]]
    if [item["id"] for item in prototypes] != ordered_ids:
        fail("prototypes must follow batch and card order")


def render(project_dir: Path) -> None:
    manifest_path = project_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate(project_dir, data)
    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "__BOARD_DATA_JSON__"
    if template.count(marker) != 1:
        fail("dashboard template must contain exactly one data marker")
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    embedded = embedded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    (project_dir / "index.html").write_text(template.replace(marker, embedded), encoding="utf-8")
    print(f"Rendered {project_dir / 'index.html'} ({len(data['batches'])} batches, {len(data['prototypes'])} prototypes)")


def init(project_dir: Path, title: str, brief: str) -> None:
    if project_dir.exists() and any(project_dir.iterdir()):
        fail(f"project directory is not empty: {project_dir}")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "prototypes").mkdir(exist_ok=True)
    (project_dir / "previews").mkdir(exist_ok=True)
    data = {"schemaVersion": 1, "project": {"title": title, "brief": brief}, "batches": [], "prototypes": []}
    (project_dir / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(project_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init")
    init_parser.add_argument("project_dir", type=Path)
    init_parser.add_argument("--title", required=True)
    init_parser.add_argument("--brief", required=True)
    render_parser = commands.add_parser("render")
    render_parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            init(args.project_dir, args.title, args.brief)
        else:
            render(args.project_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"board.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
