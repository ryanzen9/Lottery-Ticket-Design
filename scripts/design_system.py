"""Persist style decisions and synchronize Tailwind v4 sources into local HTML."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets"
CDN = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"
FIELDS = ("layout", "style", "palette", "elements", "motion", "typography", "interaction")
START = "<!-- ltd:design-system:start -->"
END = "<!-- ltd:design-system:end -->"
MARKER = "<!-- __DESIGN_SYSTEM_HEAD__ -->"


def path_in(project: Path, relative: str, suffix: str, *, exists: bool = True) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("design-system path must be a nonempty string")
    rel = Path(relative)
    target = project / rel
    if rel.is_absolute() or ".." in rel.parts or rel.suffix != suffix or target.is_symlink():
        raise ValueError(f"unsafe design-system path: {relative}")
    if not target.resolve().is_relative_to(project.resolve()):
        raise ValueError(f"design-system path escapes project: {relative}")
    if exists and not target.is_file():
        raise ValueError(f"missing design-system file: {relative}")
    return target


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(item: dict) -> dict:
    if not all(isinstance(item.get(k), str) and item[k].strip() for k in FIELDS):
        raise ValueError("record layout, style, palette, elements, motion, typography and interaction before design")
    return {k: item[k] for k in FIELDS}


def history(project: Path, item: dict) -> tuple[Path, dict]:
    rel = f"prototypes/{item['id']}/style-history.json"
    path = path_in(project, rel, ".json", exists=False)
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"designId": item["id"], "records": []}
    if not isinstance(value, dict) or value.get("designId") != item["id"] or not isinstance(value.get("records"), list):
        raise ValueError(f"invalid style history for {item['id']}")
    for index, record in enumerate(value["records"], 1):
        if not isinstance(record, dict) or record.get("revision") != index or record.get("stage") not in ("draft", "anchored"):
            raise ValueError(f"invalid style revision for {item['id']}")
    return path, value


def record(item: dict, records: list, stage: str, description: str) -> dict:
    if not description.strip():
        raise ValueError("a design description or evolution reason is required")
    return {"revision": len(records) + 1, "stage": stage,
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "description": description, "style": snapshot(item),
            "parentIds": item.get("parentIds", []), "exceptions": item.get("styleExceptions", [])}


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(project: Path, design_id: str, description: str, parent_id: str | None = None) -> None:
    manifest = project / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in data["prototypes"]}
    if not re.fullmatch(r"P-\d{3,}", design_id) or design_id not in items:
        raise ValueError("prepare requires an existing manifest design id")
    item = items[design_id]
    snapshot(item)
    folder = path_in(project, f"prototypes/{design_id}/design.css", ".css", exists=False).parent
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "screens").mkdir(exist_ok=True)
    history_path, log = history(project, item)
    if log["records"] and log["records"][-1]["stage"] == "draft":
        raise ValueError("finish the pending draft with anchor before preparing another style change")
    css_path = folder / "design.css"
    source = ASSETS / "design-system-template.css"
    if parent_id:
        parent = items.get(parent_id)
        if not parent or parent_id not in item.get("parentIds", []) or parent["batch"] >= item["batch"]:
            raise ValueError("--from must be a selected parent from an earlier batch")
        if css_path.exists():
            raise ValueError("inheritance will not overwrite an existing design.css")
        validate(project, parent)
        source = path_in(project, parent["designSystem"], ".css")
    # Write the style decision before creating or editing its stylesheet.
    log["records"].append(record(item, log["records"], "draft", description))
    dump(history_path, log)
    if not css_path.exists():
        css_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    item["designSystem"] = f"prototypes/{design_id}/design.css"
    item["styleHistory"] = f"prototypes/{design_id}/style-history.json"
    dump(manifest, data)
    print(f"Recorded draft for {design_id}; edit {css_path}, then anchor before writing screens.")


def anchor(project: Path, design_id: str, description: str | None = None) -> None:
    data = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    item = next((x for x in data["prototypes"] if x["id"] == design_id), None)
    if item is None:
        raise ValueError(f"unknown design id: {design_id}")
    history_path, log = history(project, item)
    if not log["records"] or log["records"][-1]["stage"] != "draft":
        raise ValueError("run prepare with the style metadata and change description first")
    css = path_in(project, item.get("designSystem", ""), ".css")
    if "@theme" not in css.read_text(encoding="utf-8"):
        raise ValueError("design.css must define Tailwind v4 @theme tokens")
    current = record(item, log["records"], "anchored", description or log["records"][-1]["description"])
    current["designSystemSha256"] = fingerprint(css)
    log["records"].append(current)
    dump(history_path, log)
    print(f"Anchored {design_id} at style revision {current['revision']}.")


def validate(project: Path, item: dict) -> dict:
    folder = f"prototypes/{item['id']}"
    if item.get("designSystem") != f"{folder}/design.css" or item.get("styleHistory") != f"{folder}/style-history.json":
        raise ValueError(f"{item['id']} requires its own design.css and style-history.json; run prepare")
    css = path_in(project, item["designSystem"], ".css")
    _, log = history(project, item)
    if not log["records"] or log["records"][-1]["stage"] != "anchored":
        raise ValueError(f"{item['id']} has no anchored style; finish design.css and run anchor")
    latest = log["records"][-1]
    if latest.get("style") != snapshot(item) or latest.get("parentIds") != item.get("parentIds", []) or latest.get("exceptions") != item.get("styleExceptions", []):
        raise ValueError(f"{item['id']} metadata changed after anchoring; record the evolution with prepare and anchor")
    if latest.get("designSystemSha256") != fingerprint(css):
        raise ValueError(f"{item['id']} design.css changed after anchoring; record the evolution with prepare and anchor")
    return latest


def ensure_shell(project: Path) -> Path:
    target = path_in(project, "design.css", ".css", exists=False)
    if not target.exists():
        source = (ASSETS / "design-system-template.css").read_text(encoding="utf-8")
        source += "\n" + (ASSETS / "shell-layout.css").read_text(encoding="utf-8")
        target.write_text(source, encoding="utf-8")
    return target


def inject(source: str, css: Path, page: Path) -> str:
    if "</head>" not in source:
        raise ValueError(f"page needs an HTML head: {page}")
    content = css.read_text(encoding="utf-8")
    if re.search(r"</style", content, re.I):
        raise ValueError("design.css may not contain a closing HTML style tag")
    relative = Path(os.path.relpath(css, page.parent)).as_posix()
    block = (f'{START}\n<script src="{CDN}"></script>\n'
             f'<link rel="stylesheet" href="{html.escape(relative, quote=True)}" data-ltd-design-source>\n'
             f'<style type="text/tailwindcss" data-ltd-design-system>\n{content}\n</style>\n{END}')
    pattern = re.escape(START) + r".*?" + re.escape(END)
    if START in source:
        return re.sub(pattern, lambda _: block, source, count=1, flags=re.S)
    # Normalize a manually added copy of the same CDN to a single managed load.
    source = re.sub(r'<script\b[^>]*src=[\"\']' + re.escape(CDN) + r'[\"\'][^>]*>\s*</script>', '', source)
    if MARKER in source:
        return source.replace(MARKER, block, 1)
    return source.replace("</head>", block + "\n</head>", 1)
