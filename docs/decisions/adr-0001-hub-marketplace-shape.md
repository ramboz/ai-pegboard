---
status: Accepted
last_verified: 2026-10-12
---

# ADR-0001: One catalog, three generated host descriptors, plugins stay in their repos

## Status

Accepted (2026-10-12)

## Context

jig, servo, and shaper each ship as a plugin for Claude Code and Codex (jig also
for GitHub Copilot CLI), and each repository carries its own single-plugin
marketplace pointer. A user who wants all of them registers three marketplaces
per host, and every new plugin adds another. More plugins are in the pipeline.

The three hosts each discover a marketplace at their own canonical path and
speak their own `plugins[].source` dialect, verified against the shipped CLIs
on 2026-10-12 (Claude Code 2.1.241, Codex 0.133.0, Copilot CLI 1.0.93):

| Host | Descriptor path | Remote-plugin source form |
|---|---|---|
| Claude Code | `.claude-plugin/marketplace.json` | `git-subdir {url, path, ref, sha}`; whole repo: `github {repo, ref, sha}` |
| Codex | `.agents/plugins/marketplace.json` | `git-subdir {url, path, ref, sha}` + required `policy`, `category`; whole repo: `url {url, ref, sha}` |
| Copilot CLI | `.github/plugin/marketplace.json` | `github {repo, path, ref, sha}` |

Codex and Copilot both fall back to `.claude-plugin/marketplace.json` when
their own file is absent, but neither documents accepting the other dialects,
and jig already hit a fall-through bug (jig bug 035) from sharing a descriptor.

## Options considered

### A. Vendor every plugin's host packages into the hub (git subtree / sync job)

Pros: each host reads plain relative sources; works for local-path
registration. Cons: duplicates every package in a second repo, needs a sync
job per plugin per release, and makes the hub the thing that drifts.
**Rejected.**

### B. One shared `.claude-plugin/marketplace.json` for all hosts

Pros: one file. Cons: relies on undocumented fall-through, cannot carry Codex's
required `policy`/`category`, and Copilot does not document `git-subdir`.
**Rejected** (the lesson of jig bug 035).

### C. Hand-maintain three descriptors

Pros: no tooling. Cons: three places to edit per plugin per release; they
drift. **Rejected.**

### D (chosen). `catalog.json` → generated per-host descriptors, remote sources only

One hand-edited catalog entry per plugin (repo, release pin, host package
paths). A stdlib-only renderer emits the three native descriptors and the
README table; `--check` is the CI drift guard. Plugins never leave their
repositories; the hub fetches each committed `hosts/<host>/` package at a
pinned tag + SHA.

## Decision

Option D. Supporting decisions:

- **Stable channel.** The hub pins every plugin to its latest GitHub release
  (tag + 40-char SHA on every host). Each plugin repo's own marketplace stays
  the moving dev/latest channel. `scripts/bump_catalog.py` + the daily
  `bump-catalog` workflow re-pin via PR; `"pin": false` opts a plugin into
  tracking its default branch.
- **Per-host presence is explicit.** A plugin appears in a host's descriptor
  only when its catalog entry declares a package path for that host. (At
  acceptance servo and shaper had no `hosts/copilot/`; see Amendments.)
- **Name.** The marketplace is `ai-pegboard`, repo and manifest alike: a
  pegboard is where a shop hangs its tools in view, and the `ai-` prefix says
  which shop. Collision check on 2026-10-12: `ai-pegboard` had no GitHub repo,
  user, or org, and was free on npm, PyPI, and crates.io; the bare `pegboard`
  is taken on npm and PyPI and used by ~230 GitHub repos. The name is half of
  every plugin id (`jig@ai-pegboard`) and must stay stable.

## Consequences

- Adding a plugin is one catalog entry plus `build_marketplaces.py`; any
  GitHub repo (including private) works.
- Users who already added a plugin's own marketplace must pick one id per
  plugin (`jig@jig` vs `jig@ai-pegboard`) because both load the `jig:` prefix.
- **Copilot caveat (verified 2026-10-12):** when the hub is registered from a
  *local path*, Copilot loads plugins "live" from that directory and prunes
  remote-sourced ones after a reported-successful install. Registering from
  GitHub (`copilot plugin marketplace add ramboz/ai-pegboard`) is the supported
  path; `smoke_hosts.py --source` exists to prove it after the first push.
- Claude Code validates `--strict`; the renderer emits only documented fields.

## Amendments

- **2026-10-12** — servo v0.11.0 and shaper v0.5.0 shipped committed
  `hosts/copilot/` packages, so every catalog plugin now renders on all three
  hosts. Adding a host is one `hosts.<host>.path` line on the catalog entry;
  `bump_catalog.py` only re-pins hosts that are already declared, so a newly
  shipped host package still needs that line added by hand.
