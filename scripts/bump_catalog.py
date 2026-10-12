#!/usr/bin/env python3
"""bump_catalog.py — pin every catalog plugin to its latest GitHub release.

For each plugin in catalog.json whose `pin` is not false:
    1. GET /repos/{repo}/releases/latest             → tag (e.g. v2.16.2) and version
    2. GET /repos/{repo}/git/ref/tags/{tag}          → commit SHA (annotated tags are peeled)
    3. GET /repos/{repo}/contents/{path}?ref={tag}   → every declared host package exists at that tag
then rewrites catalog.json's `version` / `ref` / `sha`. Run
`python3 scripts/build_marketplaces.py` afterwards to regenerate the descriptors.

Honours GH_TOKEN / GITHUB_TOKEN (unauthenticated GitHub API allows 60 requests/hour).

Usage:
    python3 scripts/bump_catalog.py [--plugin NAME ...] [--dry-run]

Exit codes: 0 updated or already current · 1 a declared host package is missing at the
release tag (that plugin is left untouched) · 2 GitHub API / network error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
_KEY_ORDER = (
    "name", "description", "repo", "homepage", "category", "keywords",
    "pin", "version", "ref", "sha", "hosts",
)


class ApiError(RuntimeError):
    pass


def _api(path: str) -> Optional[Dict[str, Any]]:
    """GET an API path; None on 404, ApiError on anything else that fails."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-pegboard-bump-catalog",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ApiError(f"GET {path} → HTTP {exc.code}: {exc.reason}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f"GET {path} failed: {exc}") from None


def resolve_release(repo: str) -> Optional[Dict[str, str]]:
    """{'tag', 'version', 'sha'} for the repo's latest release, or None when it has none."""
    release = _api(f"/repos/{repo}/releases/latest")
    if release is None:
        return None
    tag = release["tag_name"]
    ref = _api(f"/repos/{repo}/git/ref/tags/{tag}")
    if ref is None:
        raise ApiError(f"{repo}: release {tag} exists but its tag ref is missing")
    obj = ref["object"]
    sha = obj["sha"]
    if obj["type"] == "tag":  # annotated tag → peel to the commit
        peeled = _api(f"/repos/{repo}/git/tags/{sha}")
        if peeled is None:
            raise ApiError(f"{repo}: cannot peel annotated tag {tag}")
        sha = peeled["object"]["sha"]
    return {"tag": tag, "version": tag[1:] if tag.startswith("v") else tag, "sha": sha}


def missing_packages(repo: str, tag: str, hosts: Dict[str, Dict[str, str]]) -> List[str]:
    missing = []
    for host, spec in hosts.items():
        path = spec["path"]
        if path in ("", "."):
            continue
        if _api(f"/repos/{repo}/contents/{path}?ref={tag}") is None:
            missing.append(f"{host}: {path}")
    return missing


def _ordered(plugin: Dict[str, Any]) -> Dict[str, Any]:
    ordered = {key: plugin[key] for key in _KEY_ORDER if key in plugin}
    ordered.update({key: value for key, value in plugin.items() if key not in ordered})
    return ordered


def bump(catalog_path: Path, only: Optional[List[str]] = None, dry_run: bool = False, out=None) -> int:
    out = out or sys.stdout
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    exit_code = 0
    changed = False
    for index, plugin in enumerate(catalog["plugins"]):
        name = plugin["name"]
        if only and name not in only:
            continue
        if plugin.get("pin") is False:
            out.write(f"{name}: pin=false, tracking the default branch — skipped\n")
            continue
        release = resolve_release(plugin["repo"])
        if release is None:
            out.write(f"{name}: {plugin['repo']} has no GitHub release yet — skipped\n")
            continue
        missing = missing_packages(plugin["repo"], release["tag"], plugin["hosts"])
        if missing:
            out.write(f"{name}: {release['tag']} lacks declared host packages ({'; '.join(missing)}) — NOT bumped\n")
            exit_code = 1
            continue
        before = (plugin.get("version"), plugin.get("ref"), plugin.get("sha"))
        after = (release["version"], release["tag"], release["sha"])
        if before == after:
            out.write(f"{name}: already at {release['tag']}\n")
            continue
        out.write(f"{name}: {before[1] or 'unpinned'} → {release['tag']} ({release['sha'][:12]})\n")
        plugin["version"], plugin["ref"], plugin["sha"] = after
        catalog["plugins"][index] = _ordered(plugin)
        changed = True
    if changed and not dry_run:
        catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out.write("catalog.json updated — now run: python3 scripts/build_marketplaces.py\n")
    elif changed:
        out.write("dry run: catalog.json not written\n")
    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", default=str(ROOT / "catalog.json"))
    parser.add_argument("--plugin", action="append", help="only bump this plugin (repeatable)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        return bump(Path(args.catalog), only=args.plugin, dry_run=args.dry_run)
    except ApiError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
