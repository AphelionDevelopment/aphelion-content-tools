# Maintainer Guide

This guide is for maintainers responsible for the catalog, the game-repository build integration, and
the release/bootstrap path. Writer-facing workflow is covered in the
[writer guide](writer-guide.md); architecture and implementation history are in
[architecture/](architecture/).

## Architecture summary

`aphelion-lore-tools` is the source of truth for catalog snapshots, writer groups, reviews,
assignments, and per-record overrides. `Meridian-Rift` supplies BYOND/DMI assets for catalog
generation and icon previews, and receives only the generated runtime artifact
(`modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm`) through the staged export
workflow — it never receives editor code or raw per-record content. Authentication, pushes, pull
requests, and complex merge conflicts are handled in GitHub Desktop; this tool only does local status,
branch, and commit operations.

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
  reaches the Tools panel's run log automatically, since it's just CLI stdout.

## Group and review oversight

Groups (`tools/lore_editor/content/groups/` in standalone mode) drive keyword/type-path matching and
the review queue's filters. As a maintainer, periodically check the group definitions still match
intent — a keyword that's too broad silently pulls unrelated targets into a group's review queue.
Reviews and per-record overrides are otherwise writer-owned; maintainers don't need to touch them
directly.

## Git operation safety

`git_adapter.py` serializes every multi-step operation (`repository_status`, `create_branch`,
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

[`Launch Lore Tools.cmd`](../Launch%20Lore%20Tools.cmd) calls
[`tools/launcher/launch.ps1`](../tools/launcher/launch.ps1), which:

1. Looks for a compatible Python (3.11+, with Pillow) via `python.exe`, `py -3`, or a previously
   installed private runtime, in that order.
2. If none is found, asks before downloading the pinned installer named in
   [`tools/launcher/runtime_manifest.json`](../tools/launcher/runtime_manifest.json), verifies its
   Authenticode signature is a valid Python Software Foundation signature before running it, and
   installs it per-user into `%LOCALAPPDATA%\AphelionLoreTools\runtime` (no PATH changes, no
   all-users install). Declining leaves manual-install instructions on screen and changes nothing.
3. Resolves the game-checkout path (from `%LOCALAPPDATA%\AphelionLoreTools\settings.json`, a nearby
   `Meridian-Rift` folder, or a manual prompt) and persists it for next time.
4. Starts `tools/lore_editor/serve.py` on a loopback port and opens the browser to it.

To change the pinned Python version, edit `runtime_manifest.json`'s `version`, `installer_url`, and
`signature_subject_contains` fields together — an installer whose signature doesn't match the expected
subject is rejected outright, so all three must stay consistent.

## Verification checklist before calling a change complete

```powershell
python -m unittest discover -s tools/lore_editor/tests -p 'test_*.py'
node --check tools/lore_editor/web/app.js
python tools/lore_editor/cli.py generate --repo-root .
python tools/lore_editor/cli.py validate --repo-root . --check-generated
git diff --check
```

Plus, when BYOND is available: a Meridian-Rift compile and the AutoWiki CI job (see above). Leave all
changes uncommitted unless a commit or push has been explicitly requested.
