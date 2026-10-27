#!/usr/bin/env python3
"""Create and render a self-contained prototype selection board."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
import design_system as ds
import export_design


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_DIR / "assets" / "dashboard-template.html"
DESIGN_TEMPLATE = SKILL_DIR / "assets" / "design-board-template.html"
WEB_VIEWER_TEMPLATE = SKILL_DIR / "assets" / "web-viewer-template.html"
IPHONE_VIEWER_TEMPLATE = SKILL_DIR / "assets" / "iphone-18-pro-viewer-template.html"
SYSTEM_TEMPLATE = SKILL_DIR / "assets" / "design-system-board-template.html"
ID_PATTERN = re.compile(r"P-\d{3,}$")
SCREEN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*$")
VIEWER_TYPES = ("web", "iphone-18-pro")
REQUIRED_TEXT = (
    "title", "direction", "summary", "layout", "palette",
    "interaction", "responsive", "rationale", "file",
)
KEY_DESIGN_FIELDS = ("layout", "style", "palette", "elements", "motion", "typography", "interaction")


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
    if not isinstance(data, dict) or data.get("schemaVersion") not in (1, 2, 3):
        fail("manifest.json requires schemaVersion: 1, 2 or 3")
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
        mode = batch.get("mode", "explore")
        if mode not in ("explore", "refine"):
            fail(f"batch {number} mode must be explore or refine")
        valid_count = isinstance(ids, list) and (len(ids) == 1 if mode == "refine" else 6 <= len(ids) <= 10)
        if not valid_count or len(set(ids)) != len(ids):
            fail(f"batch {number} requires {'1 unique id for refinement' if mode == 'refine' else '6–10 unique ids'}")
        if mode == "refine" and not batch.get("stageId"):
            fail(f"refinement batch {number} requires stageId")
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
        if data["schemaVersion"] >= 2 and not all(
            isinstance(item.get(key), str) and item[key].strip() for key in KEY_DESIGN_FIELDS
        ):
            fail(f"prototype {proto_id} requires layout, style, palette, elements, motion, typography and interaction")
        if design_brief is not None and not all(
            isinstance(item.get(key), str) and item[key].strip() for key in ("style", "motion")
        ):
            fail(f"prototype {proto_id} requires style and motion")
        if not isinstance(item.get("tags"), list) or any(not isinstance(tag, str) for tag in item["tags"]):
            fail(f"prototype {proto_id} requires string tags")
        for field in ("style", "elements", "motion", "typography"):
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
            if data["schemaVersion"] >= 2:
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
        if data["schemaVersion"] >= 3 or item.get("designSystem"):
            ds.validate(project_dir, item)
            exceptions = item.get("styleExceptions", [])
            if not isinstance(exceptions, list) or any(not isinstance(x, dict) or not all(isinstance(x.get(k), str) and x[k].strip() for k in ("scope", "reason")) for x in exceptions):
                fail(f"prototype {proto_id} styleExceptions require scope and reason")
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
            if screen.get("viewer", "web") not in VIEWER_TYPES:
                fail(f"prototype {proto_id} screen {screen_id} requires viewer: web or iphone-18-pro")
            if "statusBar" in screen and screen["statusBar"] not in ("light", "dark"):
                fail(f"prototype {proto_id} screen {screen_id} has invalid statusBar")
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
    validate_stages(data, id_to_batch)


def validate_stages(data: dict, id_to_batch: dict) -> None:
    stages = data.get("stages", [])
    if not isinstance(stages, list):
        fail("stages must be an array")
    lookup = {}
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str) or not re.fullmatch(r"S-\d{3,}", stage["id"]) or stage["id"] in lookup:
            fail("stage ids must be unique S-NNN values")
        if not isinstance(stage.get("title"), str) or not stage["title"].strip():
            fail(f"stage {stage['id']} requires title")
        if any(not isinstance(stage.get(key), str) or stage[key] not in id_to_batch for key in ("baseId", "currentId", "acceptedId")):
            fail(f"stage {stage['id']} references an unknown prototype")
        if stage.get("status") not in ("ready", "refining") or type(stage.get("revision")) is not int or stage["revision"] < 1:
            fail(f"stage {stage['id']} requires ready/refining status and a positive revision")
        if stage["status"] == "ready" and stage["currentId"] != stage["acceptedId"]:
            fail(f"ready stage {stage['id']} must point to its accepted draft")
        if stage["status"] == "refining" and stage["currentId"] == stage["acceptedId"]:
            fail(f"refining stage {stage['id']} requires a new draft awaiting acceptance")
        lookup[stage["id"]] = stage
    active = data["project"].get("activeStageId")
    if active is not None and (not isinstance(active, str) or active not in lookup):
        fail("project.activeStageId must reference a known stage")
    selection_revision = data["project"].get("stageSelectionRevision", 0)
    if type(selection_revision) is not int or selection_revision < 0:
        fail("project.stageSelectionRevision must be a nonnegative integer")
    for batch in data["batches"]:
        stage_id = batch.get("stageId")
        if not stage_id:
            if batch.get("stageBaseId"):
                fail(f"batch {batch['number']} stageBaseId requires stageId")
            continue
        if not isinstance(stage_id, str) or stage_id not in lookup:
            fail(f"batch {batch['number']} references an unknown stage")
        base = batch.get("stageBaseId")
        if not isinstance(base, str) or base not in id_to_batch or id_to_batch[base] >= batch["number"] or base not in batch.get("parentIds", []):
            fail(f"batch {batch['number']} requires an earlier stageBaseId in parentIds")
        members = {lookup[stage_id]["baseId"]} | {proto_id for entry in data["batches"] if entry.get("stageId") == stage_id and entry.get("mode") == "refine" and entry["number"] < batch["number"] for proto_id in entry["ids"]}
        if base not in members:
            fail(f"batch {batch['number']} stageBaseId must belong to its stage")
        for item in data["prototypes"]:
            if item["batch"] == batch["number"] and base not in item["parentIds"]:
                fail(f"prototype {item['id']} must inherit its stage baseline")
    for stage in stages:
        members = {stage["baseId"]} | {proto_id for batch in data["batches"] if batch.get("stageId") == stage["id"] and batch.get("mode") == "refine" for proto_id in batch["ids"]}
        if stage["currentId"] not in members or stage["acceptedId"] not in members:
            fail(f"stage {stage['id']} current/accepted draft must belong to that stage")


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
    shell_css = ds.ensure_shell(project_dir)
    design_template = DESIGN_TEMPLATE.read_text(encoding="utf-8")
    viewer_templates = {
        "web": WEB_VIEWER_TEMPLATE.read_text(encoding="utf-8"),
        "iphone-18-pro": IPHONE_VIEWER_TEMPLATE.read_text(encoding="utf-8"),
    }
    for item in data["prototypes"]:
        if "screens" not in item:
            continue
        folder = Path(item["file"]).parent
        system_files = {}
        if item.get("designSystem"):
            design_css = ds.path_in(project_dir, item["designSystem"], ".css")
            for screen in item["screens"]:
                screen_path = project_dir / screen["file"]
                screen_path.write_text(ds.inject(screen_path.read_text(encoding="utf-8"), design_css, screen_path), encoding="utf-8")
            current_style = ds.validate(project_dir, item)
            system_path = project_dir / folder / "system.html"
            safe_generated_file(project_dir, (folder / "system.html").as_posix(), ".html")
            system_source = embed(SYSTEM_TEMPLATE.read_text(encoding="utf-8"), "__SYSTEM_DATA_JSON__", {
                "designId": item["id"], "revision": current_style["revision"],
                "description": current_style["description"], "style": current_style["style"],
            })
            system_path.write_text(ds.inject(system_source, design_css, system_path), encoding="utf-8")
            system_files = {"systemFile": "system.html", "systemCss": design_css.read_text(encoding="utf-8")}
        viewer_dir = project_dir / folder / "viewers"
        viewer_dir.mkdir(exist_ok=True)
        screens = []
        for screen in item["screens"]:
            local_screen = dict(screen)
            local_screen["file"] = Path(screen["file"]).relative_to(folder).as_posix()
            viewer_type = screen.get("viewer", "web")
            viewer_relative = Path("viewers") / f"{screen['id']}.html"
            viewer_project_path = (folder / viewer_relative).as_posix()
            safe_generated_file(project_dir, viewer_project_path, ".html")
            viewer_payload = {
                "designId": item["id"],
                "designTitle": item["title"],
                "screenTitle": screen["title"],
                "screenFile": "../" + local_screen["file"],
                "statusBar": screen.get("statusBar", "dark"),
            }
            viewer_path = project_dir / viewer_project_path
            viewer_source = embed(viewer_templates[viewer_type], "__VIEWER_DATA_JSON__", viewer_payload)
            viewer_path.write_text(ds.inject(viewer_source, shell_css, viewer_path), encoding="utf-8")
            local_screen["viewer"] = viewer_type
            local_screen["viewerFile"] = viewer_relative.as_posix()
            if screen.get("preview"):
                local_screen["preview"] = Path(screen["preview"]).relative_to(folder).as_posix()
            screens.append(local_screen)
        payload = {"projectTitle": data["project"]["title"],
                   "skeletonDemo": data["project"].get("dashboardSkeleton") is True, "design": {
            "id": item["id"], "title": item["title"], "direction": item["direction"],
            "summary": item["summary"], "screens": screens,
            "exportFile": f"../../exports/{item['id']}.zip",
            "stageAction": f"../../index.html?stage={item['id']}#stages",
            **system_files,
            **{key: item.get(key, "") for key in KEY_DESIGN_FIELDS},
        }}
        board_path = project_dir / item["file"]
        board_source = embed(design_template, "__DESIGN_DATA_JSON__", payload)
        board_path.write_text(ds.inject(board_source, shell_css, board_path), encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    handoff_script = (SKILL_DIR / "assets/iteration-handoff.js").read_text(encoding="utf-8")
    if "</script" in handoff_script.lower():
        fail("iteration-handoff.js may not contain a closing script tag")
    template = template.replace("/* __ITERATION_HANDOFF_JS__ */", handoff_script, 1)
    dashboard_data = {**data, "prototypes": [{**item, "exportFile": f"exports/{item['id']}.zip"} for item in data["prototypes"]]}
    dashboard_path = project_dir / "index.html"
    dashboard_path.write_text(ds.inject(embed(template, "__BOARD_DATA_JSON__", dashboard_data), shell_css, dashboard_path), encoding="utf-8")
    for item in data["prototypes"]:
        export_design.build(project_dir, data, item)
    count = sum("screens" in item for item in data["prototypes"])
    print(f"Rendered {project_dir / 'index.html'} ({len(data['batches'])} batches, {len(data['prototypes'])} designs, {count} design boards)")


def init(project_dir: Path, title: str, brief: str) -> None:
    if project_dir.exists() and any(project_dir.iterdir()):
        fail(f"project directory is not empty: {project_dir}")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "prototypes").mkdir(exist_ok=True)
    (project_dir / "previews").mkdir(exist_ok=True)
    data = {"schemaVersion": 3, "project": {"title": title, "brief": brief}, "batches": [], "prototypes": []}
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
    prepare_parser = commands.add_parser("prepare", help="record style metadata before editing a design system")
    prepare_parser.add_argument("project_dir", type=Path)
    prepare_parser.add_argument("--id", required=True)
    prepare_parser.add_argument("--description", required=True)
    prepare_parser.add_argument("--from", dest="parent_id")
    anchor_parser = commands.add_parser("anchor", help="anchor design.css before writing screens")
    anchor_parser.add_argument("project_dir", type=Path)
    anchor_parser.add_argument("--id", required=True)
    anchor_parser.add_argument("--description")
    args = parser.parse_args()
    try:
        if args.command == "init":
            init(args.project_dir, args.title, args.brief)
        elif args.command == "prepare":
            ds.prepare(args.project_dir, args.id, args.description, args.parent_id)
        elif args.command == "anchor":
            ds.anchor(args.project_dir, args.id, args.description)
        else:
            render(args.project_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"board.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
