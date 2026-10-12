# ai-pegboard

> The pegboard the jig family hangs on — **jig**, **servo**, **shaper**, and the
> tools in the pipeline — one marketplace for Claude Code, Codex, and GitHub
> Copilot CLI. Add it once, install any plugin.

Each plugin keeps living in its own repository with its own releases. This
repository publishes only the **catalog**: three thin, generated marketplace
descriptors (one per host) that point at the committed host packages inside
those repositories. Nothing is vendored here, and no build step runs at install
time — each host fetches the pinned package straight from the plugin's repo.

## Install

Register the marketplace once per host, then install plugins as `name@ai-pegboard`.

**Claude Code**

```text
/plugin marketplace add ramboz/ai-pegboard
/plugin install jig@ai-pegboard
```

**Codex**

```bash
codex plugin marketplace add ramboz/ai-pegboard
codex plugin add jig@ai-pegboard
```

**GitHub Copilot CLI**

```bash
copilot plugin marketplace add ramboz/ai-pegboard
copilot plugin install jig@ai-pegboard
```

Swap `jig` for any plugin in the table below. A plugin only appears in a
host's descriptor when its repository ships a committed package for that host,
so `codex plugin list` / `copilot plugin marketplace browse ai-pegboard` show
exactly what will install.

## Plugins

<!-- plugins:start -->
| Plugin | What it does | Release | Claude Code | Codex | Copilot CLI |
|---|---|---|:-:|:-:|:-:|
| [jig](https://github.com/ramboz/jig) | Spec-driven, review-enforced, hook-gated AI-native development workflow: scaffold a project, split specs into slices, implement with TDD, review independently, reconcile, land. | `v2.16.2` | ✓ | ✓ | ✓ |
| [servo](https://github.com/ramboz/servo) | Closed-loop scaffolder for unattended agent operations: oracle scoring, headless agent loops, hooks, and worktree races — tailored to each project's signals. | `v0.11.0` | ✓ | ✓ | ✓ |
| [shaper](https://github.com/ramboz/shaper) | Release shaping before implementation starts: appetite, shaped bets, release cutlines, no-gos, and handoff guidance into specs. | `v0.5.0` | ✓ | ✓ | ✓ |
<!-- plugins:end -->

The table is generated from [`catalog.json`](catalog.json) — edit the catalog,
not the table.

## Release channel

The catalog pins every plugin to its **latest GitHub release** (tag + commit
SHA), so the marketplace is a stable channel: a user who installs `jig@ai-pegboard`
today and again next month gets the same bytes until this catalog moves. Each
plugin repository's own marketplace (`ramboz/jig`, `ramboz/servo`, …) remains
the moving dev/latest channel.

- **Bumping pins:** `python3 scripts/bump_catalog.py` resolves each repo's
  latest release, checks that every declared host package exists at that tag,
  and rewrites `version` / `ref` / `sha`; then `python3 scripts/build_marketplaces.py`
  regenerates the descriptors. The [`bump-catalog`](.github/workflows/bump-catalog.yml)
  workflow does both daily and opens a PR when anything moved.
- **Tracking a branch instead:** set `"pin": false` on a plugin entry (and drop
  its `ref`/`sha`). Its entries then follow the repository's default branch and
  the bump script leaves it alone — useful for a plugin that has no releases yet.
- **Picking up a new pin as a user:** refresh the marketplace, then update the
  plugin — `claude plugin marketplace update ai-pegboard` / `codex plugin marketplace upgrade`
  / `copilot plugin marketplace update ai-pegboard`, followed by the host's plugin
  update or re-add.

## Already installed from a plugin's own repository?

`jig@jig` (from `ramboz/jig`) and `jig@ai-pegboard` are different plugin ids that
load the same skills under the same `jig:` prefix, so keep **one**. To switch:

```bash
# Claude Code
claude plugin uninstall jig@jig && claude plugin marketplace remove jig
claude plugin marketplace add ramboz/ai-pegboard && claude plugin install jig@ai-pegboard
# Codex
codex plugin remove jig@jig && codex plugin marketplace remove jig
codex plugin marketplace add ramboz/ai-pegboard && codex plugin add jig@ai-pegboard
# Copilot CLI
copilot plugin uninstall jig && copilot plugin marketplace remove jig
copilot plugin marketplace add ramboz/ai-pegboard && copilot plugin install jig@ai-pegboard
```

## Adding a plugin

1. **In the plugin's repository**, ship committed, drift-guarded host packages
   and cut a release tag — the `hosts/<host>/` pattern jig, servo, and shaper
   follow ([jig ADR-0018](https://github.com/ramboz/jig/blob/main/docs/decisions/adr-0018-dual-host-generated-plugin-artifacts.md)).
   The package paths are whatever that repo's own marketplace pointers already
   use (`hosts/claude`, `hosts/codex/plugins/<name>`, `hosts/copilot`).
2. **Add one entry** to `catalog.json`:

   ```json
   {
     "name": "plane",
     "description": "One sentence, host-neutral.",
     "repo": "ramboz/plane",
     "category": "Engineering",
     "keywords": ["..."],
     "version": "0.1.0",
     "ref": "v0.1.0",
     "sha": "<40-char commit sha of the tag>",
     "hosts": {
       "claude": { "path": "hosts/claude" },
       "codex": { "path": "hosts/codex/plugins/plane" },
       "copilot": { "path": "hosts/copilot" }
     }
   }
   ```

   Omit a host the plugin does not package yet; it is simply absent from that
   host's descriptor. Use `"path": "."` when the plugin *is* the repository
   root. `python3 scripts/bump_catalog.py --plugin plane` fills in
   `version`/`ref`/`sha` for you. Any GitHub repository works, including private
   ones for users who can read them.
3. **Regenerate and verify:** `python3 scripts/build_marketplaces.py`, then
   `python3 scripts/smoke_hosts.py`. CI's drift guard refuses a PR whose
   descriptors do not match the catalog.

## How it works

```
catalog.json                      ← single source of truth (hand-edited)
scripts/build_marketplaces.py     ← renders the three descriptors + README table; --check = drift guard
scripts/bump_catalog.py           ← re-pins plugins to their latest GitHub release
scripts/smoke_hosts.py            ← registers this dir in an isolated home for each host CLI present
.claude-plugin/marketplace.json   ← GENERATED  Claude Code   plugins[].source = git-subdir {url, path, ref, sha}
.agents/plugins/marketplace.json  ← GENERATED  Codex         plugins[].source = git-subdir {url, path, ref, sha} + policy, category
.github/plugin/marketplace.json   ← GENERATED  Copilot CLI   plugins[].source = github {repo, path, ref, sha}
```

**Why three files instead of one?** Each host looks for its own descriptor
first and only falls back to `.claude-plugin/marketplace.json`, and each speaks
a different `source` dialect: Codex requires `policy` and `category`, Copilot
documents `github` + `path` but not `git-subdir`, and Claude validates fields
strictly. Committing one native descriptor per host — rendered from the same
catalog — is what the plugin repositories themselves converged on after a
fall-through bug (jig bug 035).

## Verify

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'   # renderer + catalog validation
python3 scripts/build_marketplaces.py --check            # descriptors match the catalog
claude plugin validate --strict .                        # Claude Code's own marketplace validator
python3 scripts/smoke_hosts.py                           # live `marketplace add` per installed host CLI, isolated homes
python3 scripts/smoke_hosts.py --install jig             # …plus an end-to-end install from GitHub (Claude Code, Codex)
python3 scripts/smoke_hosts.py --source ramboz/ai-pegboard --install jig   # after pushing: the hosted marketplace, all hosts
```

Copilot CLI only installs from a marketplace it fetched from GitHub or a git
URL; registered from a local path it lists the plugins but loads nothing, so
the Copilot install leg needs `--source`. Decisions and the per-host source
dialects are recorded in [ADR-0001](docs/decisions/adr-0001-hub-marketplace-shape.md).

## Name

A pegboard is the wall a workshop hangs its tools on: everything in view, grab
what you need, and the empty outlines show what is still to come. That is what
this repository is for jig, servo, shaper, and the tools in the pipeline (gauge,
vellum, …). The `ai-` prefix says which shop; the bare word is already taken on
npm, PyPI, and a couple of hundred GitHub repositories. The marketplace `name`
in `catalog.json` is what users type after `@`, so keep it stable — renaming it
changes every plugin id.
