# Maintainer Guide

This guide is for maintainers responsible for the catalog, the Content Graph, the game-repository
build integration, and the release/bootstrap path. Writer-facing Lore Editor workflow is covered in
the [writer guide](writer-guide.md); architecture and implementation history are in
[architecture/](architecture/).

## Repository structure

`aphelion-content-tools` is a multi-tool suite, not a single app:

- `webapp/` — the shared shell every tool runs inside: the local HTTP server (`server.py`,
  `serve.py`), the generic Git adapter (`git_adapter.py`), the background job runner (`tooling.py`),
  the game-checkout identity check (`game_repository.py`), generic manifest/JSON-storage primitives,
  and the **Home page** (`web/index.html`, `app.js`, `styles.css`), served at `/` — repository status,
  local Git actions, and the cross-tool "Cache and Storage Management" job list live here, not inside
  any one tool.
- `tools/lore_editor/` — the Lore Editor tool: its own domain logic, content, catalog snapshot, and its
  own page (`tools/lore_editor/web/index.html`, `app.js`), served by the shared shell at `/lore-editor`.
  Imports the shared pieces from `webapp/` rather than owning them.
- `tools/content_graph/` — the Content Graph tool: scanner, marker parser, its own manifest shape, and
  its own standalone page (`tools/content_graph/web/graph.html`), served by the shared shell at `/graph`
  but with no JS/CSS dependency on any other tool's page.

Each tool registers its own `ToolDefinition`s (see `tool_definitions.py` in each tool folder); the
shell combines them into one background-job registry so Home's "Cache and Storage Management" panel and
`/api/tools` list every tool's actions together, without either tool importing the other's code.

Each page's `.js` file is a plain script (no bundler, no `<script type="module">`), but ends with a
guarded block —`if (typeof module !== 'undefined' && module.exports) { module.exports = {...}; }`— that
exports its pure, DOM-free functions for testing. This only activates under Node's CommonJS `require()`;
browsers never see it. The matching top-level browser-only calls (element lookups, the auto-init call)
are guarded the same way (`typeof document !== 'undefined'`) so `require()`-ing the file under Node
doesn't throw. See `web/tests/*.test.js` next to each page's script, run via `node --test`.

## Architecture summary (Lore Editor)

The `tools/lore_editor/content/` tree is the source of truth for catalog snapshots, writer groups,
reviews, assignments, and per-record overrides. `Meridian-Rift` supplies BYOND/DMI assets for catalog
generation and icon previews, and receives only the generated runtime artifact
(`modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm`) through the staged export
workflow — it never receives editor code or raw per-record content. Authentication, pushes, pull
requests, and complex merge conflicts are handled in GitHub Desktop; this tool only does local status,
branch, and commit operations.

## Content Graph

`tools/content_graph/scanner.py` walks a game checkout's `modular_nova/modules/*` and
`modular_aphelion/modules/*` directories (module nodes), `modular_nova/master_files/**` and
`modular_aphelion/master_files/**` (override nodes, mapped to their mirrored core path), and the
`code/` tree for `NOVA EDIT`/`APHELION EDIT` marker comments (`tools/content_graph/markers.py`).

The marker parser is deliberately tolerant: real markers in Meridian-Rift use `START` and `BEGIN`
interchangeably, many are single-line with no block at all, and — per a real scan — **the large
majority carry only a free-text reason, not a module id**. A marker only becomes a graph edge
(module → core file) when its label resolves to a real module directory; everything else lands in the
`unresolved_markers` list instead of being silently dropped or mis-attributed. Don't expect the graph's
edge count to reflect the true edit count — check `manifest.marker_count` vs. the graph's edge count
for the gap, and use the Unresolved markers panel to see the rest.

Scanning is explicit and cached, not automatic: use the **Scan modular content** tool button (or
`python tools/content_graph/cli.py scan --repo-root . --game-repo <path>`), which validates the
checkout identity the same way the Lore Editor does (`webapp/game_repository.py`), then writes
`tools/content_graph/cache/index.json` and `manifest.json` (gitignored — regenerate rather than commit
them). A real scan of Meridian-Rift takes a few seconds. The graph page reads the cache; it never scans
on page load.

## Refreshing the catalog

Run this whenever the game repository's target list changes (new items, renamed types, etc.):

```bash
python tools/lore_editor/cli.py catalog-refresh --repo-root . --game-repo <path-to-Meridian-Rift>
```

This writes `tools/lore_editor/catalog/targets.json` and its provenance manifest — nothing in the game
checkout is modified. Writers pick this up automatically the next time they load or refresh the page.

Two safeguards apply whenever `--game-repo` is passed (to `catalog-refresh`, and always for
`prepare-export`/`apply-export`):

- **Checkout identity.** `validate_game_repository()` rejects the path if `tgstation.dme` is missing
  (a fast check that the directory is even a tgstation-family checkout), and — if the path is a Git
  repository with an `origin` remote configured — if that remote's URL doesn't contain
  "meridian-rift". A checkout with no Git remote configured is accepted on the content-marker check
  alone, since there's nothing further to verify.
- **Drift reporting.** `catalog-refresh` prints a summary comparing the catalog snapshot before and
  after the refresh: type paths **removed** from the game repository, type paths that **changed**
  (label, field profile, editable root, parent type, or base name/description), and which existing
  overrides now reference a removed-or-changed target ("stale" overrides worth reviewing). This
  reaches the Home page's Cache and Storage Management run log automatically, since it's just CLI
  stdout.

## Group and review oversight

Groups (`tools/lore_editor/content/groups/` in standalone mode) drive keyword/type-path matching and
the review queue's filters. As a maintainer, periodically check the group definitions still match
intent — a keyword that's too broad silently pulls unrelated targets into a group's review queue.
Reviews and per-record overrides are otherwise writer-owned; maintainers don't need to touch them
directly.

## Git operation safety

`webapp/git_adapter.py` — shared by every tool — serializes every multi-step operation (`repository_status`, `create_branch`,
`stage_and_commit`) with a per-repository-path lock, so two concurrent requests against the same
checkout (e.g. two browser tabs) can't interleave their Git index changes — different repositories are
never blocked on each other. Output is also bounded: Git error messages are truncated past 8,000
characters, and a status response lists at most 2,000 changed files (`truncated_change_count` reports
how many were left off). `open_in_github_desktop` is deliberately not locked — it only launches a
detached GUI process and never touches the working tree or index.

## The staged export mechanism

`prepare-export` and `apply-export` (exposed in the UI as **Prepare export** / **Apply selected
export**, and directly via the CLI) are deliberately split:

```bash
python tools/lore_editor/cli.py prepare-export --repo-root . --game-repo <path> [--stage-root <path>]
python tools/lore_editor/cli.py apply-export --stage <stage-directory> --game-repo <path>
```

`prepare-export` validates the tool-repo corpus, generates the DM artifact, and writes it plus a
manifest (tool revision, tool branch, catalog hash, game revision, entry/type-path lists, generated
artifact hash, and the game artifact's hash *at prepare time*) into a new timestamped directory under
`tools/lore_editor/stages/`. It never touches the game checkout.

`apply-export` re-validates all of the following against the *current* game checkout before writing
anything, and refuses (leaving the game checkout untouched) if any fail:

- the game checkout is clean (no uncommitted changes, no Git conflicts),
- the game checkout's current revision still matches the manifest's `game_repo_revision`,
- the game checkout's current generated-artifact hash still matches the manifest's
  `base_artifact_sha256` (`None` if the artifact didn't exist yet),
- the module directory (`modular_aphelion/modules/lore_overhaul/code/`) exists.

If everything holds, it atomically replaces the generated artifact and returns its path. See
[test_export.py](../tools/lore_editor/tests/test_export.py) for the exact refusal behavior.

After a successful apply, the server automatically opens the game checkout in GitHub Desktop as a
best-effort convenience step (`open_in_github_desktop(game_repo_root)`). If that fails — GitHub
Desktop isn't installed, say — the apply itself is still reported as successful; the response carries
`opened_in_github_desktop: false` and a `github_desktop_error` message instead, and the writer opens
it manually.

## Game-repository build integration

Three files in `Meridian-Rift` are intentionally touched by this migration, and nothing else should
be:

- **`tools/build/build.ts`** — adds `modular_aphelion/**` to the DreamMaker watch globs so the build
  picks up changes under the module. It does not reference this tool's paths.
- **`tgstation.dme`** — includes exactly five files under
  `modular_aphelion/modules/lore_overhaul/code/`: `catalog_probe.dm`, `lore_entry.dm`, `autowiki.dm`,
  `autowiki_tests.dm`, `generated_lore_overrides.dm`.
- **`code/modules/autowiki/autowiki.dm`** — skips the abstract `/datum/autowiki/lore_overhaul` base
  type when generating wiki pages, so only its generated subtypes publish.

`.github/workflows/autowiki.yml` is deliberately **unmodified** — it stays schedule/`workflow_dispatch`
-only and gated on the `AUTOWIKI_USERNAME` secret being set, exactly as before this migration. AutoWiki
publication must never run from a writer's local editor session.

Verify the integration with (from a Meridian-Rift checkout; BYOND does not need to be on PATH — pass
its full path if `dm.exe`/`dreamdaemon.exe` aren't found automatically, e.g.
`C:\Program Files (x86)\BYOND\bin`):

```powershell
& "<path-to-BYOND>\bin\dm.exe" tgstation.dme     # plain compile check
tools\build\build.bat --ci autowiki               # full AutoWiki generation, same as CI
```

A clean plain compile prints `0 errors` for `tgstation.dmb` (warnings from unrelated existing code are
expected and not a regression signal by themselves — compare against a compile from before your
change).

`build.bat --ci autowiki` additionally boots the compiled server headlessly and closes it once
initialization finishes, producing `data/autowiki_edits.txt` and `data/autowiki_files/`. On a Windows
machine, `dreamdaemon.exe -close`'s own shutdown exit code (observed: 144) is not zero, and the Juke
build tooling — written for the Linux CI runner, where this apparently returns 0 — reports the target
as failed regardless of whether the run actually succeeded. To tell a real failure from this known
quirk, don't trust the reported exit code alone: check `data/logs/ci/runtime.log` for errors and
confirm `data/autowiki_edits.txt` was produced with the content you expect (it will only contain
lore-overhaul pages for overrides that have `wiki.enabled` set — an override with no `wiki` field
produces no AutoWiki output by design). Clean up `data/logs/ci`, `data/autowiki_edits.txt`,
`data/autowiki_files`, `tgstation.test.*`, and `tgstation.dmb` afterward — none of them are meant to
be committed (`tgstation.dmb` and `data/**/*` are already gitignored).

## Release and bootstrap path

[`Launch Aphelion Content Tools.cmd`](../Launch%20Aphelion%20Content%20Tools.cmd) calls
[`tools/launcher/launch.ps1`](../tools/launcher/launch.ps1), which:

1. Looks for a compatible Python (3.11+, with Pillow) via `python.exe`, `py -3`, or a previously
   installed private runtime, in that order.
2. If none is found, asks before downloading the pinned installer named in
   [`tools/launcher/runtime_manifest.json`](../tools/launcher/runtime_manifest.json), verifies its
   Authenticode signature is a valid Python Software Foundation signature before running it, and
   installs it per-user into `%LOCALAPPDATA%\AphelionContentTools\runtime` (no PATH changes, no
   all-users install). Declining leaves manual-install instructions on screen and changes nothing.
3. Resolves the game-checkout path (from `%LOCALAPPDATA%\AphelionContentTools\settings.json`, a nearby
   `Meridian-Rift` folder, or a manual prompt) and persists it for next time.
4. Starts `webapp/serve.py` on a loopback port and opens the browser to it.

To change the pinned Python version, edit `runtime_manifest.json`'s `version`, `installer_url`, and
`signature_subject_contains` fields together — an installer whose signature doesn't match the expected
subject is rejected outright, so all three must stay consistent.

## Verification checklist before calling a change complete

```powershell
python -m unittest discover -s tools/lore_editor/tests -p 'test_*.py'
python -m unittest discover -s webapp/tests -p 'test_*.py'
python -m unittest discover -s tools/content_graph/tests -p 'test_*.py'
node --check webapp/web/app.js
node --check tools/lore_editor/web/app.js
node --check tools/content_graph/web/graph.js
node --test webapp/web/tests/app.test.js tools/lore_editor/web/tests/app.test.js tools/content_graph/web/tests/graph.test.js
python tools/lore_editor/cli.py generate --repo-root .
python tools/lore_editor/cli.py validate --repo-root . --check-generated
git diff --check
```

Plus, when BYOND is available: a Meridian-Rift compile and the AutoWiki CI job (see above). Leave all
changes uncommitted unless a commit or push has been explicitly requested.
