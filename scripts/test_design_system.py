import contextlib
import copy
import io
import json
import re
from pathlib import Path
import tempfile
import unittest

import board
import design_system as ds


class DesignSystemWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.data = json.loads((board.SKILL_DIR / "assets/manifest-example.json").read_text())
        self.data["schemaVersion"] = 3
        self.write_manifest()
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def write_manifest(self):
        ds.dump(self.project / "manifest.json", self.data)

    def prepare(self, item):
        ds.prepare(self.project, item["id"], "Initial direction recorded before CSS and screens")

    def write_screens(self, item):
        for screen in item["screens"]:
            path = self.project / screen["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((board.SKILL_DIR / "assets/screen-template.html").read_text())

    def test_record_anchor_and_render_share_one_css_source(self):
        for item in self.data["prototypes"]:
            self.prepare(item)
            log = json.loads((self.project / f"prototypes/{item['id']}/style-history.json").read_text())
            self.assertEqual(log["records"][0]["stage"], "draft")
            self.assertFalse((self.project / item["screens"][0]["file"]).exists())
            ds.anchor(self.project, item["id"])
            self.write_screens(item)
        board.render(self.project)
        css = self.project / "prototypes/P-001/design.css"
        original = css.read_bytes()
        screen = self.project / self.data["prototypes"][0]["screens"][0]["file"]
        html = screen.read_text()
        self.assertIn('href="../design.css"', html)
        self.assertIn(css.read_text(), html)
        self.assertTrue((css.parent / "system.html").is_file())
        detail = (css.parent / "index.html").read_text()
        payload = json.loads(re.search(r'<script type="application/json" id="design-data">(.*?)</script>', detail, re.S).group(1))
        self.assertEqual(payload["design"]["systemCss"], css.read_text())
        board.render(self.project)
        self.assertEqual(screen.read_text().count(ds.START), 1)
        self.assertEqual(screen.read_text().count(ds.CDN), 1)
        self.assertEqual(css.read_bytes(), original)
        manifest = json.loads((self.project / "manifest.json").read_text())
        manifest["prototypes"][0]["palette"] = "Changed without recording"
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            board.validate(self.project, manifest)

    def test_unrecorded_css_drift_is_rejected_and_history_is_appended(self):
        item = self.data["prototypes"][0]
        self.prepare(item)
        ds.anchor(self.project, item["id"])
        saved = json.loads((self.project / "manifest.json").read_text())["prototypes"][0]
        css = self.project / saved["designSystem"]
        css.write_text(css.read_text() + "\n/* unrecorded change */\n")
        with self.assertRaisesRegex(ValueError, "changed after anchoring"):
            ds.validate(self.project, saved)
        path, log = ds.history(self.project, saved)
        previous = copy.deepcopy(log["records"])
        ds.prepare(self.project, item["id"], "Record the next evolution")
        ds.anchor(self.project, item["id"])
        updated = json.loads(path.read_text())
        self.assertEqual(updated["records"][:2], previous)
        self.assertEqual(len(updated["records"]), 4)

    def test_parent_inheritance_copies_without_editing_parent(self):
        parent = self.data["prototypes"][0]
        self.prepare(parent)
        ds.anchor(self.project, parent["id"])
        data = json.loads((self.project / "manifest.json").read_text())
        child = copy.deepcopy(parent)
        child.update(id="P-007", batch=2, parentIds=[parent["id"]])
        data["prototypes"].append(child)
        ds.dump(self.project / "manifest.json", data)
        parent_css = self.project / f"prototypes/{parent['id']}/design.css"
        original = parent_css.read_bytes()
        ds.prepare(self.project, "P-007", "Evolve the selected parent", parent["id"])
        child_css = self.project / "prototypes/P-007/design.css"
        self.assertEqual(child_css.read_bytes(), original)
        child_css.write_text(child_css.read_text() + "\n/* new direction */\n")
        self.assertEqual(parent_css.read_bytes(), original)
        ds.anchor(self.project, "P-007")
        with self.assertRaisesRegex(ValueError, "earlier batch"):
            ds.prepare(self.project, "P-002", "invalid parent", "P-007")

    def test_legacy_projects_render_without_new_required_files(self):
        self.data["schemaVersion"] = 2
        for item in self.data["prototypes"]:
            item.pop("designSystem", None)
            item.pop("styleHistory", None)
            self.write_screens(item)
        self.write_manifest()
        board.render(self.project)
        self.assertIn(ds.CDN, (self.project / "index.html").read_text())
        self.assertFalse((self.project / "prototypes/P-001/style-history.json").exists())


if __name__ == "__main__":
    unittest.main()
