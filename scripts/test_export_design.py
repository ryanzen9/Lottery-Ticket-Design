import contextlib
import copy
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from zipfile import ZipFile

import board
import design_system as ds
import export_design


class ExportDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.data = json.loads((board.SKILL_DIR / "assets/manifest-example.json").read_text())
        self.data["project"]["dashboardSkeleton"] = True
        ds.dump(self.project / "manifest.json", self.data)
        with contextlib.redirect_stdout(io.StringIO()):
            for item in self.data["prototypes"]:
                ds.prepare(self.project, item["id"], "Record initial style")
                ds.anchor(self.project, item["id"])
                for screen in item["screens"]:
                    path = self.project / screen["file"]
                    path.parent.mkdir(exist_ok=True, parents=True)
                    path.write_text('<html><head></head><body>Original prototype</body></html>')
            self.data = json.loads((self.project / "manifest.json").read_text())
            board.render(self.project)
        self.item = self.data["prototypes"][0]

    def test_archive_has_exact_sources_metadata_and_standalone_viewing_tree(self):
        original = (self.project / self.item["screens"][0]["file"]).read_bytes()
        with ZipFile(self.project / "exports/P-001.zip") as package:
            names = set(package.namelist())
            self.assertIsNone(package.testzip())
            for path in ["index.html", "metadata.json", "serve.py", "_runtime/tailwindcss-browser-4.3.3.js", "_runtime/TAILWIND-LICENSE.txt", self.item["designSystem"], self.item["styleHistory"]]:
                self.assertIn("P-001/" + path, names)
            self.assertFalse(any("prototypes/P-002/" in name for name in names))
            self.assertEqual(package.read("P-001/originals/" + self.item["screens"][0]["file"]), original)
            self.assertEqual(package.read("P-001/" + self.item["designSystem"]), (self.project / self.item["designSystem"]).read_bytes())
            metadata = json.loads(package.read("P-001/metadata.json"))
            self.assertEqual(metadata["design"], self.item)
            self.assertEqual(metadata["project"]["designBrief"], self.data["project"]["designBrief"])
            self.assertEqual(metadata["runtime"]["externalResources"], [])
            html = package.read("P-001/" + self.item["file"]).decode()
            payload = json.loads(re.search(r'<script type="application/json" id="design-data">(.*?)</script>', html, re.S).group(1))
            self.assertFalse(payload["skeletonDemo"])
            self.assertIsNone(payload["design"]["exportFile"])
            self.assertIn('src="../../_runtime/tailwindcss-browser-4.3.3.js"', html)
        self.assertEqual((self.project / self.item["screens"][0]["file"]).read_bytes(), original)

    def test_dependency_closure_includes_shared_css_images_modules_and_declared_assets(self):
        assets = self.project / "shared"; assets.mkdir()
        (assets / "theme.css").write_text('.hero{background:url("pixel.svg")}')
        (assets / "pixel.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (assets / "module.js").write_text('export const message = "hello";')
        (assets / "main.js").write_text('import {message} from "./module.js"; fetch("./data.json");')
        (assets / "data.json").write_text('{"ready":true}')
        (assets / "dynamic.txt").write_text('Dynamically addressed asset')
        screen = self.project / self.item["screens"][0]["file"]
        screen.write_text('<html><head><link rel="stylesheet" href="../../../shared/theme.css"></head><body><script type="module" src="../../../shared/main.js"></script><img src="https://example.com/remote.png"></body></html>')
        item = copy.deepcopy(self.item); item["exportAssets"] = ["shared/dynamic.txt"]
        destination = export_design.build(self.project, self.data, item)
        with ZipFile(destination) as package:
            for name in ['theme.css', 'pixel.svg', 'main.js', 'module.js', 'data.json', 'dynamic.txt']:
                self.assertIn('P-001/shared/' + name, package.namelist())
            metadata = json.loads(package.read('P-001/metadata.json'))
            self.assertTrue(metadata['runtime']['localServerRecommended'])
            self.assertEqual(metadata['runtime']['externalResources'], ['https://example.com/remote.png'])

    def test_missing_or_outside_dependencies_fail_without_replacing_previous_archive(self):
        archive = self.project / 'exports/P-001.zip'; saved = archive.read_bytes()
        screen = self.project / self.item['screens'][0]['file']
        for reference in ['missing.png', '../../../../outside.png']:
            screen.write_text(f'<html><head></head><body><img src="{reference}"></body></html>')
            with self.assertRaisesRegex(ValueError, 'local project file'):
                export_design.build(self.project, self.data, self.item)
            self.assertEqual(archive.read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
