#!/usr/bin/env python3
"""smoke_hosts.py — prove each host CLI can register this marketplace and see its plugins.

Runs every host CLI found on PATH against a fresh, isolated config home so your
real Claude / Codex / Copilot setup is never touched:

    Claude Code   CLAUDE_CONFIG_DIR   claude plugin validate --strict · marketplace add · marketplace list
    Codex         CODEX_HOME          codex plugin marketplace add · plugin list
    Copilot CLI   COPILOT_HOME        copilot plugin marketplace add · marketplace browse

With `--install NAME` it also installs that plugin from the marketplace, which
fetches the pinned package from GitHub (network).

By default the marketplace registered is THIS checkout (a local path). Pass
`--source ramboz/ai-pegboard` (or a git URL) after pushing to register the hosted
marketplace instead — that is the only way to prove a Copilot install: Copilot
loads a local-path marketplace's plugins live from that directory and prunes
remote-sourced ones, so a local registration lists the plugins but cannot
install them.

Usage:
    python3 scripts/smoke_hosts.py [--host claude|codex|copilot ...] [--install NAME ...]
                                   [--source OWNER/REPO|URL] [--keep]

Exit codes: 0 every probed host passed · 1 a host failed. A CLI that is not
installed is reported UNAVAILABLE and does not fail the run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
HOME_VARS = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "copilot": "COPILOT_HOME"}
TIMEOUT = 300


class StepFailed(Exception):
    pass


def _run(argv: List[str], env: Dict[str, str], expect: Optional[List[str]] = None) -> str:
    try:
        proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=TIMEOUT, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        raise StepFailed(f"`{' '.join(argv)}` timed out after {TIMEOUT}s") from None
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise StepFailed(f"`{' '.join(argv)}` exited {proc.returncode}:\n{output.strip()}")
    for needle in expect or []:
        if needle not in output:
            raise StepFailed(f"`{' '.join(argv)}` output lacks {needle!r}:\n{output.strip()}")
    return output


def _plugins_for(catalog: dict, host: str) -> List[str]:
    return [p["name"] for p in catalog["plugins"] if host in p["hosts"]]


def probe(host: str, catalog: dict, home: Path, install: List[str], out, source: Optional[str] = None) -> bool:
    cli = shutil.which(host)
    if cli is None:
        out.write(f"[{host}] UNAVAILABLE — `{host}` not on PATH\n")
        return True
    env = {**os.environ, HOME_VARS[host]: str(home)}
    name = catalog["name"]
    marketplace_source = source or str(ROOT)
    available = _plugins_for(catalog, host)
    ids = [f"{p}@{name}" for p in available]
    for plugin in install:
        if plugin not in available:
            out.write(f"[{host}] SKIP  install {plugin} — no {host} package in the catalog\n")
    install = [p for p in install if p in available]
    if host == "copilot" and install and source is None:
        out.write(
            f"[{host}] SKIP  install {', '.join(install)} — Copilot prunes remote-sourced plugins of a "
            "local-path marketplace; rerun with --source OWNER/REPO once the hub is pushed\n"
        )
        install = []
    steps = []
    if host == "claude":
        steps.append(([cli, "plugin", "validate", "--strict", str(ROOT)], ["Validation passed"]))
        steps.append(([cli, "plugin", "marketplace", "add", marketplace_source], ["Successfully added marketplace"]))
        steps.append(([cli, "plugin", "marketplace", "list"], [name]))
        for plugin in install:
            steps.append(([cli, "plugin", "install", f"{plugin}@{name}"], ["Successfully installed"]))
            steps.append(([cli, "plugin", "list"], [f"{plugin}@{name}"]))
    elif host == "codex":
        steps.append(([cli, "plugin", "marketplace", "add", marketplace_source], []))
        steps.append(([cli, "plugin", "list"], ids))
        for plugin in install:
            steps.append(([cli, "plugin", "add", f"{plugin}@{name}"], []))
    elif host == "copilot":
        steps.append(([cli, "plugin", "marketplace", "add", marketplace_source], []))
        steps.append(([cli, "plugin", "marketplace", "list"], [name]))
        steps.append(([cli, "plugin", "marketplace", "browse", name], _plugins_for(catalog, host)))
        for plugin in install:
            steps.append(([cli, "plugin", "install", f"{plugin}@{name}"], []))
            steps.append(([cli, "plugin", "list"], [plugin]))
    for argv, expect in steps:
        label = " ".join(argv[1:4])
        try:
            _run(argv, env, expect)
        except StepFailed as exc:
            out.write(f"[{host}] FAIL  {label}\n{_indent(str(exc))}\n")
            return False
        out.write(f"[{host}] OK    {label}\n")
    return True


def _indent(text: str) -> str:
    return "\n".join(f"        {line}" for line in text.splitlines())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", action="append", choices=sorted(HOME_VARS), help="probe only this host (repeatable)")
    parser.add_argument("--install", action="append", default=[], help="also install this plugin (repeatable; network)")
    parser.add_argument("--source", help="register this marketplace source (OWNER/REPO or git URL) instead of this checkout")
    parser.add_argument("--keep", action="store_true", help="keep the isolated homes for inspection")
    args = parser.parse_args(argv)
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    hosts = args.host or list(HOME_VARS)
    work = Path(tempfile.mkdtemp(prefix="ai-pegboard-smoke-"))
    ok = True
    for host in hosts:
        home = work / host
        home.mkdir()
        ok = probe(host, catalog, home, args.install, sys.stdout, source=args.source) and ok
    if args.keep:
        sys.stdout.write(f"isolated homes kept under {work}\n")
    else:
        shutil.rmtree(work, ignore_errors=True)
    sys.stdout.write("RESULT: PASS\n" if ok else "RESULT: FAIL\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
