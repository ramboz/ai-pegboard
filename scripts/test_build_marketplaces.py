"""Unit tests for build_marketplaces.py — run: python3 -m unittest discover -s scripts -p 'test_*.py'"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_marketplaces as bm  # noqa: E402

SHA = "bccb6be1cf0f3b62c471869b7d9208928fa323c0"
SAMPLE = {
    "name": "ai-pegboard",
    "displayName": "ai-pegboard",
    "description": "test catalog",
    "owner": {"name": "ramboz", "url": "https://github.com/ramboz"},
    "plugins": [
        {
            "name": "jig",
            "description": "spec workflow",
            "repo": "ramboz/jig",
            "keywords": ["workflow"],
            "version": "2.16.2",
            "ref": "v2.16.2",
            "sha": SHA,
            "hosts": {
                "claude": {"path": "hosts/claude"},
                "codex": {"path": "hosts/codex/plugins/jig"},
                "copilot": {"path": "hosts/copilot"},
            },
        },
        {
            "name": "servo",
            "description": "eval loops",
            "repo": "ramboz/servo",
            "pin": False,
            "hosts": {"claude": {"path": "hosts/claude"}, "codex": {"path": "hosts/codex/plugins/servo"}},
        },
        {
            "name": "solo",
            "description": "a whole-repo plugin",
            "repo": "someone/solo",
            "hosts": {"claude": {"path": "."}, "codex": {"path": "."}, "copilot": {"path": "."}},
        },
    ],
}
README = "# x\n\n## Plugins\n<!-- plugins:start -->\nstale\n<!-- plugins:end -->\n\ntail\n"


class _TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write_catalog(SAMPLE)
        (self.root / "README.md").write_text(README, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write_catalog(self, data):
        (self.root / "catalog.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def build(self, check=False):
        out = io.StringIO()
        code = bm.build(self.root, check=check, out=out)
        return code, out.getvalue()

    def manifest(self, host):
        return json.loads((self.root / bm.TARGETS[host]).read_text(encoding="utf-8"))

    def entry(self, host, name):
        return next(p for p in self.manifest(host)["plugins"] if p["name"] == name)


class RenderTests(_TempRepo):
    def test_build_writes_three_descriptors_and_readme_table(self):
        code, out = self.build()
        self.assertEqual(code, 0)
        for host in bm.HOSTS:
            self.assertTrue((self.root / bm.TARGETS[host]).exists(), host)
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("stale", readme)
        self.assertIn("| [jig](https://github.com/ramboz/jig) |", readme)
        self.assertIn("`v2.16.2`", readme)
        self.assertIn("default branch", readme)  # servo is unpinned
        self.assertTrue(readme.endswith("\ntail\n"))

    def test_claude_entry_is_git_subdir_with_pins(self):
        self.build()
        doc = self.manifest("claude")
        self.assertEqual(doc["name"], "ai-pegboard")
        self.assertEqual(doc["owner"]["name"], "ramboz")
        jig = doc["plugins"][0]
        self.assertEqual(
            jig["source"],
            {"source": "git-subdir", "url": "https://github.com/ramboz/jig.git", "path": "hosts/claude", "ref": "v2.16.2", "sha": SHA},
        )
        self.assertEqual(jig["version"], "2.16.2")
        self.assertEqual(jig["category"], "Engineering")
        self.assertEqual(jig["homepage"], "https://github.com/ramboz/jig")

    def test_codex_entry_has_policy_and_dot_slash_path(self):
        self.build()
        doc = self.manifest("codex")
        self.assertEqual(doc["interface"], {"displayName": "ai-pegboard"})
        jig = doc["plugins"][0]
        self.assertEqual(jig["source"]["source"], "git-subdir")
        self.assertEqual(jig["source"]["path"], "./hosts/codex/plugins/jig")
        self.assertEqual(jig["source"]["ref"], "v2.16.2")
        self.assertEqual(jig["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertEqual(jig["category"], "Engineering")

    def test_copilot_entry_is_github_with_path(self):
        self.build()
        doc = self.manifest("copilot")
        self.assertEqual(doc["owner"], {"name": "ramboz"})  # url is not a Copilot owner field
        self.assertEqual(doc["metadata"]["description"], "test catalog")
        jig = doc["plugins"][0]
        self.assertEqual(
            jig["source"],
            {"source": "github", "repo": "ramboz/jig", "path": "hosts/copilot", "ref": "v2.16.2", "sha": SHA},
        )

    def test_host_without_package_is_omitted(self):
        self.build()
        self.assertEqual([p["name"] for p in self.manifest("copilot")["plugins"]], ["jig", "solo"])
        self.assertEqual([p["name"] for p in self.manifest("claude")["plugins"]], ["jig", "servo", "solo"])

    def test_root_package_uses_each_hosts_whole_repo_form(self):
        self.build()
        claude = self.entry("claude", "solo")["source"]
        codex = self.entry("codex", "solo")["source"]
        copilot = self.entry("copilot", "solo")["source"]
        self.assertEqual(claude, {"source": "github", "repo": "someone/solo"})
        self.assertEqual(codex, {"source": "url", "url": "https://github.com/someone/solo.git"})
        self.assertEqual(copilot, {"source": "github", "repo": "someone/solo"})

    def test_unpinned_plugin_has_no_ref_or_sha(self):
        self.build()
        for host in ("claude", "codex"):
            servo = self.entry(host, "servo")
            self.assertNotIn("ref", servo["source"])
            self.assertNotIn("sha", servo["source"])
            self.assertNotIn("version", servo)

    def test_check_reports_drift_then_passes_after_rebuild(self):
        code, out = self.build(check=True)
        self.assertEqual(code, 1)
        self.assertIn("STALE", out)
        self.assertIn(".claude-plugin/marketplace.json", out)
        self.assertFalse((self.root / bm.TARGETS["claude"]).exists(), "--check must never write")
        self.build()
        code, out = self.build(check=True)
        self.assertEqual(code, 0, out)
        target = self.root / bm.TARGETS["codex"]
        target.write_text(target.read_text(encoding="utf-8").replace("AVAILABLE", "NOT_AVAILABLE"), encoding="utf-8")
        code, out = self.build(check=True)
        self.assertEqual(code, 1)
        self.assertIn(".agents/plugins/marketplace.json", out)

    def test_rendering_is_deterministic(self):
        first = bm.render_all(self.root)
        second = bm.render_all(self.root)
        self.assertEqual(first, second)

    def test_readme_without_markers_is_left_alone(self):
        (self.root / "README.md").write_text("# plain\n", encoding="utf-8")
        self.build()
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "# plain\n")

    def test_main_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bm.main(["--root", str(self.root), "--check"]), 1)
            self.assertEqual(bm.main(["--root", str(self.root)]), 0)
            self.assertEqual(bm.main(["--root", str(self.root), "--check"]), 0)
            self.write_catalog({"name": "x"})
            self.assertEqual(bm.main(["--root", str(self.root), "--check"]), 2)


class ValidationTests(unittest.TestCase):
    def _errors(self, mutate):
        data = copy.deepcopy(SAMPLE)
        mutate(data)
        with self.assertRaises(bm.CatalogError) as ctx:
            bm.validate_catalog(data)
        return str(ctx.exception)

    def test_sample_is_valid(self):
        bm.validate_catalog(copy.deepcopy(SAMPLE))

    def test_duplicate_plugin_name(self):
        msg = self._errors(lambda d: d["plugins"][1].__setitem__("name", "jig"))
        self.assertIn("duplicate plugin name 'jig'", msg)

    def test_unknown_host(self):
        msg = self._errors(lambda d: d["plugins"][0]["hosts"].__setitem__("cursor", {"path": "x"}))
        self.assertIn("hosts.cursor: unknown host", msg)

    def test_bad_paths(self):
        for bad in ("./hosts/claude", "/hosts", "hosts/", "a/../b", "a\\b"):
            msg = self._errors(lambda d, bad=bad: d["plugins"][0]["hosts"]["claude"].__setitem__("path", bad))
            self.assertIn("hosts.claude.path", msg, bad)

    def test_bad_sha_and_repo(self):
        msg = self._errors(lambda d: d["plugins"][0].__setitem__("sha", "abc"))
        self.assertIn("sha: must be a full 40-character", msg)
        msg = self._errors(lambda d: d["plugins"][0].__setitem__("repo", "jig"))
        self.assertIn("repo: required GitHub 'owner/repo'", msg)

    def test_missing_owner_and_empty_plugins_report_together(self):
        def mutate(d):
            del d["owner"]
            d["plugins"] = []
        msg = self._errors(mutate)
        self.assertIn("owner.name: required", msg)
        self.assertIn("plugins: required non-empty array", msg)


if __name__ == "__main__":
    unittest.main()
