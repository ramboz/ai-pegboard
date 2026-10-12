#!/usr/bin/env python3
"""build_marketplaces.py — render the per-host marketplace descriptors from catalog.json.

`catalog.json` is the single source of truth: one entry per plugin, naming the
GitHub repo, the release pin, and the committed host package path per host.
Every host reads its OWN descriptor at its OWN canonical path and speaks its
own `plugins[].source` dialect, so the three files are generated, never
hand-edited:

    host          descriptor                         plugin source
    Claude Code   .claude-plugin/marketplace.json    git-subdir {url, path, ref, sha}
    Codex         .agents/plugins/marketplace.json   git-subdir {url, path, ref, sha} + policy/category
    Copilot CLI   .github/plugin/marketplace.json    github {repo, path, ref, sha}

A plugin whose package IS its repo root (host path "." ) renders as each
host's whole-repo form instead (Claude/Copilot `github`, Codex `url`).

The script also refreshes the plugin table in README.md between the
`<!-- plugins:start -->` / `<!-- plugins:end -->` markers.

Usage:
    python3 scripts/build_marketplaces.py            # write descriptors + README table in place
    python3 scripts/build_marketplaces.py --check    # drift guard (read-only): exit 1 when stale

Exit codes: 0 ok · 1 stale (--check) · 2 catalog.json invalid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CATALOG = "catalog.json"
README = "README.md"
HOSTS = ("claude", "codex", "copilot")
HOST_LABELS = {"claude": "Claude Code", "codex": "Codex", "copilot": "Copilot CLI"}
TARGETS: Dict[str, Path] = {
    "claude": Path(".claude-plugin", "marketplace.json"),
    "codex": Path(".agents", "plugins", "marketplace.json"),
    "copilot": Path(".github", "plugin", "marketplace.json"),
}
TABLE_START = "<!-- plugins:start -->"
TABLE_END = "<!-- plugins:end -->"
DEFAULT_CATEGORY = "Engineering"
CODEX_POLICY = {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CatalogError(ValueError):
    """catalog.json failed validation; the message lists every problem found."""


# --------------------------------------------------------------------------- catalog


def load_catalog(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CatalogError(f"{path}: not found") from None
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path}: invalid JSON: {exc}") from None
    validate_catalog(data)
    return data


def validate_catalog(data: Any) -> None:
    if not isinstance(data, dict):
        raise CatalogError("catalog.json must be a JSON object")
    errors: List[str] = []
    name = data.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        errors.append(
            "name: required; letters, digits, '.', '_', '-' and must start alphanumeric "
            "(users type it after '@' when installing)"
        )
    owner = data.get("owner")
    if not isinstance(owner, dict) or not _non_empty_str(owner.get("name")):
        errors.append("owner.name: required")
    if not _non_empty_str(data.get("description")):
        errors.append("description: required")
    for key in ("displayName", "version"):
        if key in data and not _non_empty_str(data[key]):
            errors.append(f"{key}: must be a non-empty string when set")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        errors.append("plugins: required non-empty array")
    else:
        seen: set = set()
        for index, plugin in enumerate(plugins):
            errors.extend(_validate_plugin(index, plugin, seen))
    if errors:
        raise CatalogError("catalog.json is invalid:\n  - " + "\n  - ".join(errors))


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_plugin(index: int, plugin: Any, seen: set) -> List[str]:
    tag = f"plugins[{index}]"
    if not isinstance(plugin, dict):
        return [f"{tag}: must be an object"]
    errors: List[str] = []
    name = plugin.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        errors.append(f"{tag}.name: required; letters, digits, '.', '_', '-', starting alphanumeric")
    elif name in seen:
        errors.append(f"{tag}.name: duplicate plugin name {name!r}")
    else:
        seen.add(name)
    repo = plugin.get("repo")
    if not isinstance(repo, str) or not _REPO_RE.match(repo):
        errors.append(f"{tag}.repo: required GitHub 'owner/repo'")
    if not _non_empty_str(plugin.get("description")):
        errors.append(f"{tag}.description: required")
    for key in ("version", "ref", "category", "homepage"):
        if key in plugin and plugin[key] is not None and not _non_empty_str(plugin[key]):
            errors.append(f"{tag}.{key}: must be a non-empty string when set")
    sha = plugin.get("sha")
    if sha is not None and (not isinstance(sha, str) or not _SHA_RE.match(sha)):
        errors.append(f"{tag}.sha: must be a full 40-character lowercase hex commit SHA")
    if "pin" in plugin and not isinstance(plugin["pin"], bool):
        errors.append(f"{tag}.pin: must be true or false")
    keywords = plugin.get("keywords")
    if keywords is not None and (
        not isinstance(keywords, list) or not all(isinstance(k, str) and k for k in keywords)
    ):
        errors.append(f"{tag}.keywords: must be an array of non-empty strings")
    hosts = plugin.get("hosts")
    if not isinstance(hosts, dict) or not hosts:
        errors.append(f"{tag}.hosts: required non-empty object keyed by {', '.join(HOSTS)}")
        return errors
    for host, spec in hosts.items():
        if host not in HOSTS:
            errors.append(f"{tag}.hosts.{host}: unknown host (expected one of {', '.join(HOSTS)})")
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
            errors.append(f"{tag}.hosts.{host}.path: required string (package dir relative to the repo root, or '.')")
            continue
        errors.extend(_validate_path(f"{tag}.hosts.{host}.path", spec["path"]))
    return errors


def _validate_path(tag: str, path: str) -> List[str]:
    if path in ("", "."):
        return []
    if path.startswith("/") or path.startswith("./") or path.endswith("/"):
        return [
            f"{tag}: write the package path relative to the repo root, with no leading './' or '/' "
            f"and no trailing '/' (got {path!r})"
        ]
    if "\\" in path or any(segment in ("", "..") for segment in path.split("/")):
        return [f"{tag}: must not contain '..', empty segments, or backslashes (got {path!r})"]
    return []


# --------------------------------------------------------------------------- rendering


def _git_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def _homepage(plugin: Dict[str, Any]) -> str:
    return plugin.get("homepage") or f"https://github.com/{plugin['repo']}"


def _pin_fields(plugin: Dict[str, Any]) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    if plugin.get("ref"):
        fields["ref"] = plugin["ref"]
    if plugin.get("sha"):
        fields["sha"] = plugin["sha"]
    return fields


def _host_path(plugin: Dict[str, Any], host: str) -> Optional[str]:
    spec = plugin["hosts"].get(host)
    if spec is None:
        return None
    return spec["path"]


def _is_root(path: str) -> bool:
    return path in ("", ".")


def render_claude(catalog: Dict[str, Any]) -> Dict[str, Any]:
    plugins = []
    for plugin in catalog["plugins"]:
        path = _host_path(plugin, "claude")
        if path is None:
            continue
        if _is_root(path):
            source: Dict[str, Any] = {"source": "github", "repo": plugin["repo"]}
        else:
            source = {"source": "git-subdir", "url": _git_url(plugin["repo"]), "path": path}
        source.update(_pin_fields(plugin))
        entry: Dict[str, Any] = {"name": plugin["name"], "description": plugin["description"]}
        if plugin.get("version"):
            entry["version"] = plugin["version"]
        entry["category"] = plugin.get("category", DEFAULT_CATEGORY)
        if plugin.get("keywords"):
            entry["keywords"] = list(plugin["keywords"])
        entry["homepage"] = _homepage(plugin)
        entry["repository"] = f"https://github.com/{plugin['repo']}"
        entry["source"] = source
        plugins.append(entry)
    return {
        "name": catalog["name"],
        "description": catalog["description"],
        "owner": dict(catalog["owner"]),
        "plugins": plugins,
    }


def render_codex(catalog: Dict[str, Any]) -> Dict[str, Any]:
    plugins = []
    for plugin in catalog["plugins"]:
        path = _host_path(plugin, "codex")
        if path is None:
            continue
        if _is_root(path):
            source: Dict[str, Any] = {"source": "url", "url": _git_url(plugin["repo"])}
        else:
            source = {"source": "git-subdir", "url": _git_url(plugin["repo"]), "path": f"./{path}"}
        source.update(_pin_fields(plugin))
        plugins.append(
            {
                "name": plugin["name"],
                "source": source,
                "policy": dict(CODEX_POLICY),
                "category": plugin.get("category", DEFAULT_CATEGORY),
            }
        )
    return {
        "name": catalog["name"],
        "interface": {"displayName": catalog.get("displayName") or catalog["name"]},
        "plugins": plugins,
    }


def render_copilot(catalog: Dict[str, Any]) -> Dict[str, Any]:
    plugins = []
    for plugin in catalog["plugins"]:
        path = _host_path(plugin, "copilot")
        if path is None:
            continue
        source: Dict[str, Any] = {"source": "github", "repo": plugin["repo"]}
        if not _is_root(path):
            source["path"] = path
        source.update(_pin_fields(plugin))
        entry: Dict[str, Any] = {"name": plugin["name"], "description": plugin["description"]}
        if plugin.get("version"):
            entry["version"] = plugin["version"]
        entry["category"] = plugin.get("category", DEFAULT_CATEGORY)
        if plugin.get("keywords"):
            entry["keywords"] = list(plugin["keywords"])
        entry["homepage"] = _homepage(plugin)
        entry["source"] = source
        plugins.append(entry)
    owner = {"name": catalog["owner"]["name"]}
    if catalog["owner"].get("email"):
        owner["email"] = catalog["owner"]["email"]
    metadata: Dict[str, Any] = {"description": catalog["description"]}
    if catalog.get("version"):
        metadata["version"] = catalog["version"]
    return {"name": catalog["name"], "owner": owner, "metadata": metadata, "plugins": plugins}


RENDERERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "claude": render_claude,
    "codex": render_codex,
    "copilot": render_copilot,
}


def dumps(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_table(catalog: Dict[str, Any]) -> str:
    header = "| Plugin | What it does | Release | " + " | ".join(HOST_LABELS[h] for h in HOSTS) + " |"
    rule = "|---|---|---|" + "|".join(":-:" for _ in HOSTS) + "|"
    rows = [header, rule]
    for plugin in catalog["plugins"]:
        release = f"`{plugin['ref']}`" if plugin.get("ref") else "default branch"
        marks = " | ".join("✓" if h in plugin["hosts"] else "—" for h in HOSTS)
        description = plugin["description"].replace("|", "\\|")
        rows.append(
            f"| [{plugin['name']}](https://github.com/{plugin['repo']}) | {description} | {release} | {marks} |"
        )
    return "\n".join(rows) + "\n"


def splice_readme(text: str, table: str) -> Optional[str]:
    """Replace the block between the table markers; None when README has no markers."""
    start = text.find(TABLE_START)
    end = text.find(TABLE_END)
    if start < 0 or end < 0 or end < start:
        return None
    head = text[: start + len(TABLE_START)]
    tail = text[end:]
    return f"{head}\n{table}{tail}"


# --------------------------------------------------------------------------- build


def render_all(root: Path) -> Dict[Path, str]:
    """Every generated file (relative path → content) for the catalog under `root`."""
    catalog = load_catalog(root / CATALOG)
    rendered: Dict[Path, str] = {TARGETS[host]: dumps(RENDERERS[host](catalog)) for host in HOSTS}
    readme = root / README
    if readme.exists():
        spliced = splice_readme(readme.read_text(encoding="utf-8"), render_table(catalog))
        if spliced is not None:
            rendered[Path(README)] = spliced
    return rendered


def build(root: Path, check: bool = False, out=None) -> int:
    out = out or sys.stdout
    rendered = render_all(root)
    stale: List[Path] = []
    for rel, text in rendered.items():
        target = root / rel
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == text:
            continue
        if check:
            stale.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        out.write(f"wrote {rel.as_posix()}\n")
    if check:
        if stale:
            out.write("STALE: generated files do not match catalog.json:\n")
            for rel in stale:
                out.write(f"  - {rel.as_posix()}\n")
            out.write("regenerate with: python3 scripts/build_marketplaces.py\n")
            return 1
        out.write("OK: marketplace descriptors and README table match catalog.json\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT), help="marketplace repo root (default: this repo)")
    parser.add_argument("--check", action="store_true", help="drift guard: compare only, never write")
    args = parser.parse_args(argv)
    try:
        return build(Path(args.root).resolve(), check=args.check)
    except CatalogError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
