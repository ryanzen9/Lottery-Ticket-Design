"""Build one portable, editable prototype archive without changing its sources."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
from zipfile import ZIP_DEFLATED, ZipFile

import design_system as ds

ASSETS = Path(__file__).resolve().parents[1] / "assets"
RUNTIME = "_runtime/tailwindcss-browser-4.3.3.js"
SKIP = {".DS_Store", "__pycache__", ".git"}
CSS_REFS = re.compile(r'''url\(\s*["']?([^\s"')]+)["']?\s*\)|@import\s+["']([^"']+)["']''', re.I)
JS_REFS = re.compile(r'''\b(?:import\s*\(|fetch\s*\(|new\s+URL\s*\()\s*["']([^"']+)["']|\b(?:import|export)\s+(?:[^;\n]*?\s+from\s*)?["']([^"']+)["']''')
TAILWIND = re.compile(r'''(<script\b[^>]*\bsrc=["'])https://cdn\.jsdelivr\.net/npm/@tailwindcss/browser@4(?:\.\d+){0,2}(?:/dist/index\.global\.js)?(["'])''', re.I)


def json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def source_file(project: Path, path: Path) -> Path:
    candidate = project / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(project) or not resolved.is_file():
        raise ValueError(f"export requires a local project file: {path}")
    for part in (candidate, *candidate.parents):
        if part == project:
            break
        if part.is_symlink():
            raise ValueError(f"export does not follow symlinks: {path}")
    return resolved


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
        self.css = []
        self.js = []
        self.active = None
        self.server = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and attrs.get("href") not in (None, "", "./"):
            raise ValueError("export requires document-relative paths instead of a base URL")
        for key in ("src", "href", "xlink:href", "poster") + (("data",) if tag == "object" else ()):
            if attrs.get(key):
                self.refs.append((attrs[key], tag == "a"))
        if attrs.get("srcset") and not attrs["srcset"].lstrip().startswith("data:"):
            self.refs.extend((part.strip().split()[0], False) for part in attrs["srcset"].split(",") if part.strip())
        if attrs.get("style"):
            self.css.append(attrs["style"])
        if tag == "style":
            self.active = self.css
        elif tag == "script" and attrs.get("type", "") in ("", "module", "text/javascript"):
            self.active = self.js
            self.server |= attrs.get("type") == "module"

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.active = None


def portable_html(text: str, path: Path, item: dict) -> str:
    runtime = Path(os.path.relpath(RUNTIME, path.parent)).as_posix()
    text = TAILWIND.sub(lambda match: match[1] + runtime + match[2], text)
    if item.get("screens") and path.as_posix() == item["file"]:
        pattern = r'(<script type="application/json" id="design-data">)(.*?)(</script>)'
        def replace_board(match):
            payload = json.loads(match[2])
            payload["skeletonDemo"] = False
            payload["design"]["exportFile"] = None
            payload["design"]["stageAction"] = None
            encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            return match[1] + encoded + match[3]
        text = re.sub(pattern, replace_board, text, count=1, flags=re.S)
        text = text.replace('href="../../index.html#prototype-grid"', 'href="../../index.html"', 1)
        text = text.replace('</svg>原型总览</a>', '</svg>导出概览</a>', 1)
    return text


def collect(project: Path, item: dict) -> tuple[dict, list, bool]:
    pending = {Path("design.css"), Path(item["file"])}
    for key in ("designSystem", "styleHistory", "tokens", "preview"):
        if item.get(key):
            pending.add(Path(item[key]))
    folder = project / "prototypes" / item["id"]
    if item.get("screens"):
        pending.update(file.relative_to(project) for file in folder.rglob("*") if file.is_file() and not SKIP.intersection(file.parts))
    extra = item.get("exportAssets", [])
    if not isinstance(extra, list) or any(not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts for path in extra):
        raise ValueError("exportAssets must list project-relative local files or directories")
    for relative in extra:
        asset = project / relative
        if asset.is_symlink() or not asset.resolve().is_relative_to(project) or not asset.exists():
            raise ValueError(f"invalid export asset: {relative}")
        if asset.is_dir():
            pending.update(file.relative_to(project) for file in asset.rglob("*") if file.is_file() and not SKIP.intersection(file.parts))
        else:
            pending.add(Path(relative))
    files, external, server = {}, set(), False
    while pending:
        path = pending.pop()
        if path.as_posix() in files:
            continue
        file = source_file(project, path)
        path = file.relative_to(project)
        if path.as_posix() in files:
            continue
        original = file.read_bytes()
        content = original
        refs = []
        if path.suffix.lower() in (".html", ".htm", ".css", ".js", ".mjs", ".svg"):
            text = original.decode("utf-8")
            css, scripts = [], []
            if path.suffix.lower() in (".html", ".htm"):
                text = portable_html(text, path, item)
                content = text.encode("utf-8")
                page = References(); page.feed(text)
                refs.extend(page.refs); css = page.css; scripts = page.js; server |= page.server
            elif path.suffix.lower() == ".css":
                css = [text]
            elif path.suffix.lower() in (".js", ".mjs"):
                scripts = [text]; server |= path.suffix.lower() == ".mjs"
            else:
                page = References(); page.feed(text); refs.extend(page.refs); css = page.css; scripts = page.js
            for block in css:
                refs.extend((match[1] or match[2], False) for match in CSS_REFS.finditer(block))
            for block in scripts:
                refs.extend((match[1] or match[2], False) for match in JS_REFS.finditer(block))
                server |= bool(re.search(r'\bfetch\s*\(|\bimport\s', block))
        files[path.as_posix()] = (original, content)
        for value, navigation in refs:
            if value == "tailwindcss" or value.startswith("tailwindcss/"):
                continue  # Built into the bundled Tailwind browser runtime.
            parsed = urlsplit(value)
            if parsed.scheme in ("http", "https") or parsed.netloc:
                if not navigation:
                    external.add(value)
                continue
            if parsed.scheme in ("data", "blob", "mailto", "tel", "javascript") or not parsed.path:
                continue
            if value == Path(os.path.relpath(RUNTIME, path.parent)).as_posix():
                continue
            if parsed.scheme:
                raise ValueError(f"export requires relative local references: {value} in {path}")
            target = Path(unquote(parsed.path))
            if target.is_absolute():
                target = Path(target.as_posix().lstrip("/")); server = True
            else:
                target = path.parent / target
            resolved = (project / target).resolve()
            if resolved == project / "index.html":
                continue  # The export supplies its own overview.
            pending.add(source_file(project, target).relative_to(project))
    return files, sorted(external), server


def entry_page(project: Path, item: dict, external: list, server: bool) -> str:
    screens = item.get("screens", [])
    links = []
    for screen in screens:
        viewer = (Path(item["file"]).parent / "viewers" / (screen["id"] + ".html")).as_posix()
        links.append(f'<a class="ds-card screen-entry" href="{html.escape(viewer, quote=True)}"><span>{html.escape(screen["title"])}</span><small>{html.escape(screen.get("viewer", "web"))} ↗</small></a>')
    system = ""
    if item.get("designSystem"):
        path = (Path(item["file"]).parent / "system.html").as_posix()
        system = f'<a class="ds-button" href="{html.escape(path, quote=True)}">设计系统</a>'
    note = ""
    if external:
        note = f'<p class="ds-copy">另有 {len(external)} 项外部资源需要联网，见 metadata.json。</p>'
    if server:
        note += '<p class="ds-copy">此原型包含模块或本地数据请求。运行 <code>python3 serve.py</code> 后，在终端显示的地址打开。</p>'
    replacements = {
        "__TITLE__": html.escape(item["title"]), "__ID__": html.escape(item["id"]),
        "__SUMMARY__": html.escape(item["summary"]), "__BOARD__": html.escape(item["file"], quote=True),
        "__SCREENS__": "\n".join(links), "__SYSTEM__": system, "__RUNTIME_NOTE__": note,
    }
    source = (ASSETS / "export-entry-template.html").read_text(encoding="utf-8")
    for key, value in replacements.items():
        source = source.replace(key, value)
    source = ds.inject(source, project / "design.css", project / "index.html")
    return portable_html(source, Path("index.html"), item)


def build(project: Path, data: dict, item: dict) -> Path:
    project = project.resolve()
    files, external, server = collect(project, item)
    packed = {}
    inventory = []
    for path, (original, content) in sorted(files.items()):
        packed[path] = content
        record = {"file": path, "sourceSha256": hashlib.sha256(original).hexdigest(), "packagedSha256": hashlib.sha256(content).hexdigest()}
        if original != content:
            record["originalFile"] = f"originals/{path}"
            packed[record["originalFile"]] = original
        inventory.append(record)
    packed[RUNTIME] = (ASSETS / "vendor/tailwindcss-browser-4.3.3.js").read_bytes()
    packed["_runtime/TAILWIND-LICENSE.txt"] = (ASSETS / "vendor/TAILWIND-LICENSE.txt").read_bytes()
    metadata = {"format": "lottery-ticket-design-export", "version": 1, "entry": "index.html",
                "project": copy.deepcopy(data["project"]), "design": copy.deepcopy(item),
                "batch": copy.deepcopy(next(batch for batch in data["batches"] if batch["number"] == item["batch"])),
                "stages": copy.deepcopy(data.get("stages", [])),
                "runtime": {"tailwindVersion": "4.3.3", "file": RUNTIME, "localServerRecommended": server, "externalResources": external},
                "files": inventory}
    metadata["project"].pop("dashboardSkeleton", None)
    packed["metadata.json"] = json_text(metadata).encode("utf-8")
    packed["index.html"] = entry_page(project, item, external, server).encode("utf-8")
    packed["serve.py"] = (ASSETS / "export-server.py").read_bytes()
    packed["README.md"] = (f'# {item["id"]} · {item["title"]}\n\n'
        '1. 解压整个文件夹，双击 `index.html`，从概览打开设计画板、各界面或设计系统。\n'
        '2. 如果原型使用 ES 模块、fetch 或根路径资源，在此目录运行 `python3 serve.py`，打开终端显示的本地地址。无需安装额外 Python 包。\n'
        '3. HTML、CSS、JS 和本地素材保持可编辑；`metadata.json` 包含需求、七项设计元数据、参考来源、父稿编号、批次反馈与文件指纹。设计系统和风格记录保留在设计目录。\n'
        '4. 为便携查看，HTML 内的 Tailwind CDN 改为包内运行时；被调整文件的精确原稿保存于 `originals/`，对应路径记录在 metadata.json。设计 CSS 与业务交互逻辑不改写。\n'
        f'5. Tailwind CSS v4.3.3 浏览器运行时及 MIT 许可证已附带。需要联网的外部资源：{len(external)} 项，详见 metadata.json。此包为静态交互原型。\n').encode("utf-8")
    directory = project / "exports"
    if directory.is_symlink():
        raise ValueError("exports directory may not be a symlink")
    directory.mkdir(exist_ok=True)
    destination = directory / f'{item["id"]}.zip'
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError(f"invalid export destination: {destination}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".zip", delete=False) as target:
            temporary = Path(target.name)
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for path, content in sorted(packed.items()):
                archive.writestr(f'{item["id"]}/{path}', content)
        temporary.replace(destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return destination
