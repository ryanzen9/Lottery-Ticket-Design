#!/usr/bin/env python3
"""Create and render a self-contained prototype selection board."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_DIR / "assets" / "dashboard-template.html"
DESIGN_TEMPLATE = SKILL_DIR / "assets" / "design-board-template.html"
ID_PATTERN = re.compile(r"P-\d{3,}$")
SCREEN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*$")
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


def safe_generated_file(project_dir: Path, value: str, suffix: str) -> None:
    if not isinstance(value, str) or not value:
        fail(f"invalid generated path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != suffix:
        fail(f"invalid generated {suffix} path: {value}")
    candidate = project_dir / relative
    if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
        fail(f"generated file path is not a regular file: {value}")
    target = candidate.resolve()
    if not target.is_relative_to(project_dir.resolve()) or not target.parent.is_dir():
        fail(f"missing or unsafe generated file directory: {value}")


def within(value: str, folder: Path) -> bool:
    return isinstance(value, str) and Path(value).is_relative_to(folder)


def validate(project_dir: Path, data: dict) -> None:
    if not isinstance(data, dict) or data.get("schemaVersion") not in (1, 2):
        fail("manifest.json requires schemaVersion: 1 or 2")
    project = data.get("project")
    if not isinstance(project, dict) or not all(isinstance(project.get(key), str) and project[key].strip() for key in ("title", "brief")):
        fail("project.title and project.brief are required")
    design_brief = project.get("designBrief")
    if design_brief is not None:
        required_brief = ("goal", "audience", "coreTasks", "platform", "stylePreferences", "interactionPreferences", "mustHave", "constraints")
        if not isinstance(design_brief, dict) or not all(
            isinstance(design_brief.get(key), str) and design_brief[key].strip() for key in required_brief
        ):
            fail("project.designBrief requires confirmed goal, audience, coreTasks, platform, stylePreferences, interactionPreferences, mustHave and constraints")
        if type(design_brief.get("prototypeCount")) is not int or not 6 <= design_brief["prototypeCount"] <= 10:
            fail("project.designBrief.prototypeCount must be 6–10")
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
        if not isinstance(ids, list) or not 6 <= len(ids) <= 10 or len(set(ids)) != len(ids):
            fail(f"batch {number} must list 6–10 unique ids")
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
        if design_brief is not None and not all(
            isinstance(item.get(key), str) and item[key].strip() for key in ("style", "motion")
        ):
            fail(f"prototype {proto_id} requires style and motion")
        if not isinstance(item.get("tags"), list) or any(not isinstance(tag, str) for tag in item["tags"]):
            fail(f"prototype {proto_id} requires string tags")
        for field in ("style", "motion"):
            if field in item and (not isinstance(item[field], str) or not item[field].strip()):
                fail(f"prototype {proto_id} has invalid {field}")
        inspirations = item.get("inspirations")
        if design_brief is not None and inspirations is None:
            fail(f"prototype {proto_id} requires inspirations")
        if inspirations is not None:
            if not isinstance(inspirations, list) or not inspirations:
                fail(f"prototype {proto_id} requires nonempty inspirations")
            for reference in inspirations:
                if not isinstance(reference, dict) or not all(
                    isinstance(reference.get(key), str) and reference[key].strip()
                    for key in ("name", "aspect", "adaptation")
                ):
                    fail(f"prototype {proto_id} has invalid inspiration")
                if "url" in reference:
                    url = reference["url"]
                    parsed = urlparse(url) if isinstance(url, str) else None
                    if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
                        fail(f"prototype {proto_id} has invalid inspiration URL")
        parents = item.get("parentIds")
        if not isinstance(parents, list) or any(parent not in batch_ids for parent in parents):
            fail(f"prototype {proto_id} has invalid parentIds")
        if any(id_to_batch[parent] >= item["batch"] for parent in parents):
            fail(f"prototype {proto_id} can only reference earlier batches")
        if item["file"] in seen_files:
            fail(f"multiple prototypes use the same file: {item['file']}")
        seen_files.add(item["file"])
        screens = item.get("screens")
        if screens is None:
            if data["schemaVersion"] == 2:
                fail(f"prototype {proto_id} requires a design folder and screens")
            safe_file(project_dir, item["file"], ".html")
            if item.get("preview"):
                safe_file(project_dir, item["preview"], ".png")
            if item.get("tokens"):
                safe_file(project_dir, item["tokens"], ".css")
            continue
        folder = Path("prototypes") / proto_id
        if item["file"] != (folder / "index.html").as_posix():
            fail(f"prototype {proto_id} board must be {folder / 'index.html'}")
        safe_generated_file(project_dir, item["file"], ".html")
        if not isinstance(screens, list) or not screens:
            fail(f"prototype {proto_id} requires at least one screen")
        screen_ids: set[str] = set()
        for screen in screens:
            if not isinstance(screen, dict) or not all(
                isinstance(screen.get(key), str) and screen[key].strip() for key in ("id", "title", "file")
            ):
                fail(f"prototype {proto_id} has invalid screen metadata")
            screen_id = screen["id"]
            if not SCREEN_ID_PATTERN.fullmatch(screen_id) or screen_id in screen_ids:
                fail(f"prototype {proto_id} has invalid or duplicate screen id: {screen_id}")
            screen_ids.add(screen_id)
            if not within(screen["file"], folder / "screens") or screen["file"] in seen_files:
                fail(f"prototype {proto_id} screen must have a unique file inside its screens folder")
            seen_files.add(screen["file"])
            safe_file(project_dir, screen["file"], ".html")
            if "summary" in screen and not isinstance(screen["summary"], str):
                fail(f"prototype {proto_id} has invalid screen summary")
            if screen.get("preview"):
                if not within(screen["preview"], folder / "previews"):
                    fail(f"prototype {proto_id} screen preview must be inside its design folder")
                safe_file(project_dir, screen["preview"], ".png")
        if item.get("preview"):
            if not within(item["preview"], folder / "previews"):
                fail(f"prototype {proto_id} preview must be inside its design folder")
            safe_file(project_dir, item["preview"], ".png")
        if item.get("tokens"):
            if not within(item["tokens"], folder):
                fail(f"prototype {proto_id} tokens must be inside its design folder")
            safe_file(project_dir, item["tokens"], ".css")
    if seen != batch_ids:
        fail(f"missing prototype entries: {', '.join(sorted(batch_ids - seen))}")
    ordered_ids = [proto_id for batch in batches for proto_id in batch["ids"]]
    if [item["id"] for item in prototypes] != ordered_ids:
        fail("prototypes must follow batch and card order")


def embed(template: str, marker: str, data: dict) -> str:
    if template.count(marker) != 1:
        fail(f"template must contain exactly one {marker} marker")
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    embedded = embedded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace(marker, embedded)


def render(project_dir: Path) -> None:
    manifest_path = project_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate(project_dir, data)
    design_template = DESIGN_TEMPLATE.read_text(encoding="utf-8")
    for item in data["prototypes"]:
        if "screens" not in item:
            continue
        folder = Path(item["file"]).parent
        screens = []
        for screen in item["screens"]:
            local_screen = dict(screen)
            local_screen["file"] = Path(screen["file"]).relative_to(folder).as_posix()
            if screen.get("preview"):
                local_screen["preview"] = Path(screen["preview"]).relative_to(folder).as_posix()
            screens.append(local_screen)
        payload = {"projectTitle": data["project"]["title"], "design": {
            "id": item["id"], "title": item["title"], "direction": item["direction"],
            "summary": item["summary"], "style": item.get("style", ""), "screens": screens,
        }}
        (project_dir / item["file"]).write_text(
            embed(design_template, "__DESIGN_DATA_JSON__", payload), encoding="utf-8"
        )
    template = TEMPLATE.read_text(encoding="utf-8")
    (project_dir / "index.html").write_text(embed(template, "__BOARD_DATA_JSON__", data), encoding="utf-8")
    count = sum("screens" in item for item in data["prototypes"])
    print(f"Rendered {project_dir / 'index.html'} ({len(data['batches'])} batches, {len(data['prototypes'])} designs, {count} design boards)")


def init(project_dir: Path, title: str, brief: str) -> None:
    if project_dir.exists() and any(project_dir.iterdir()):
        fail(f"project directory is not empty: {project_dir}")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "prototypes").mkdir(exist_ok=True)
    (project_dir / "previews").mkdir(exist_ok=True)
    data = {"schemaVersion": 2, "project": {"title": title, "brief": brief}, "batches": [], "prototypes": []}
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
