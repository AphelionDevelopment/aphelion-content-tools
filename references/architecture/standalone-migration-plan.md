# Standalone Lore Tools Migration Implementation Plan

This plan is being implemented inline in the current workspace. No subagents are part of this release workflow.

**Goal:** Move the lore editor and writer-owned data into `aphelion-lore-tools`, provide a Windows-first
double-click workflow centered on GitHub Desktop, and safely export validated runtime changes into
Meridian-Rift.

**Architecture:** The standalone repository is the canonical source for per-record lore content, catalog
snapshots, reviews, groups, and editor code. A local game checkout supplies BYOND and DMI assets. The app
uses a narrow local Git adapter for status, branches, diffs, commits, and safe export application, then
hands authentication, push, pull-request creation, and complex conflict resolution to GitHub Desktop.
Meridian-Rift receives the generated runtime DM artifact through an explicit staged export.

**Tech Stack:** Python local HTTP backend, existing browser UI, standard-library Git/process integration,
vendored or downloaded Windows Python runtime, existing DMI parser, BYOND/DreamMaker probe in the game
checkout, JSON schemas, unittest, PowerShell verification.

**Spec:** `references/architecture/standalone-migration-design.md`

## Global Constraints

- Windows-only first release.
- Do not dispatch agents; implementation is inline in the current workspace.
- Do not commit or push changes unless explicitly requested.
- Preserve unrelated dirty changes in Meridian-Rift.
- Use `apply_patch` for source edits.
- Use PowerShell for builds and runtime verification.
- Never use shell interpolation for Git arguments; use explicit argument arrays.
- Never reset, clean, force-push, silently merge, or overwrite an unexpected dirty file.
- Keep the standalone repository root limited to the launcher, README/LICENSE, `references/`, and `tools/`.
- Use tests before implementation changes where practical; add regression coverage for every migration bug.
- The app must never receive or store GitHub credentials.

---

## Task 1: Establish standalone contracts and fixtures

**Files:**

- Add the standalone Python package below `tools/lore_editor/`.
- Add schemas and fixtures below `tools/lore_editor/schemas/` and `tools/lore_editor/tests/fixtures/`.
- Add standalone ignore rules and runtime manifest under `tools/`.

**Tests first:**

- [x] Test per-record override, group, review, and assignment loading.
- [x] Test stable IDs and deterministic filenames.
- [x] Test catalog manifest hash calculation and schema version rejection.
- [x] Test stage manifest serialization and hash verification.

**Implementation:**

- [x] Define repository-relative path constants and safe path resolution.
- [x] Define record models and canonical JSON serialization.
- [x] Define catalog and export manifest models.
- [x] Make equivalent content produce deterministic ordering and hashes.

## Task 2: Migrate and load canonical content

**Files:**

- Add content loaders and migration code under `tools/lore_editor/` (with shared contracts in `app/`).
- Import current Meridian-Rift data into `tools/lore_editor/content/` and `tools/lore_editor/catalog/`.
- Update standalone schema files.

**Tests first:**

- [x] Import the current grouped entity files and compare entry counts, IDs, type paths, and field values.
- [x] Confirm groups and reviews retain all current values.
- [~] Confirm generated DM from migrated content matches the existing artifact semantically. (Investigated 2026-08-20: `git log` for `generated_lore_overrides.dm` in Meridian-Rift is empty — the file was never committed at any point in that repo's history, so there is no "existing artifact" left to diff against. User acknowledged this as moot on 2026-08-20; no further action.)
- [x] Reject duplicate IDs, duplicate field ownership, invalid catalog membership, and invalid icon records.

**Implementation:**

- [x] Convert entity arrays to one-record files while preserving IDs and values.
- [x] Convert group, review, and assignment maps to per-record files.
- [x] Move source loading, validation, taxonomy, and generation to the standalone package.
- [x] Add a one-time import command that reads a supplied game checkout without changing it.

## Task 3: Add game-checkout catalog and icon services

**Files:**

- Port and adapt catalog probe orchestration, icon preview, and source validation.
- Add game-checkout configuration and catalog snapshot handling.

**Tests first:**

- [x] Test valid and invalid game-repository paths and remote identity checks. (2026-08-20, implemented at the user's direction: added `validate_game_repository()` in `catalog.py`, checking for the `tgstation.dme` content marker and, when a Git remote is configured, that it contains "meridian-rift". Wired into `refresh_catalog` (when an explicit `--game-repo` is given), `prepare_export`, and `apply_export`. Added `repository_remote_url()` to `git_adapter.py`. Tests: `test_refresh_catalog_rejects_game_repository_missing_marker_file`, `test_refresh_catalog_rejects_game_repository_with_mismatched_remote`, `test_validate_game_repository_accepts_checkout_with_matching_remote`, `test_validate_game_repository_rejects_missing_directory` in `test_catalog.py`; `test_prepare_export_rejects_game_repository_missing_marker_file`, `test_apply_export_rejects_game_repository_missing_marker_file` in `test_export.py`; `test_repository_remote_url_returns_configured_origin`, `test_repository_remote_url_returns_none_when_no_remote_configured` in `test_git_adapter.py`. Verified live against the real Meridian-Rift checkout (accepts) and against aphelion-lore-tools itself (correctly rejects, missing tgstation.dme).)
- [x] Test snapshot loading without a game checkout.
- [x] Test catalog refresh writes only standalone data.
- [x] Test DMI preview and missing-state behavior using fixtures.

**Implementation:**

- [x] Change catalog refresh to accept `--game-repo` and write standalone `targets.json` plus manifest.
- [x] Resolve icon files against the configured game checkout rather than the tool repository.
- [x] Report stale, removed, and changed targets in validation output. (2026-08-20, implemented at the user's direction: added `compute_catalog_drift()` in `catalog.py`, comparing the catalog snapshot before and after a refresh (`read_current_targets()` reads the old snapshot before `refresh_catalog` overwrites it) and reporting removed type paths, changed type paths (label/field_profile/editable_root/parent_type/base name/base description), and which existing overrides reference a removed-or-changed target ("stale entries"). Wired into `cli.py`'s `catalog-refresh` command, which prints the drift summary after refreshing — this flows automatically into the Tools panel's captured run output since it's just CLI stdout. Scoped to `catalog-refresh` specifically (not `validate`) since drift requires a before/after comparison, which only exists around a refresh. Tests: `test_compute_catalog_drift_reports_removed_changed_and_stale_entries`, `test_compute_catalog_drift_reports_no_drift_for_identical_snapshots`, `test_read_current_targets_returns_empty_list_when_missing`, `test_read_current_targets_reads_the_committed_snapshot` in `test_catalog.py`; `test_catalog_refresh_reports_changed_and_stale_targets` in `test_cli.py`.)
- [x] Keep BYOND probe output and build artifacts confined to ignored game-checkout paths. (2026-08-20, verified: `git check-ignore -v` in Meridian-Rift confirms `data/lore_overhaul_targets.json` (the probe output, matched by `.gitignore:9:/data/**/*`) and `tgstation.dmb` (matched by `.gitignore:33:*.dmb`) are both ignored.)

## Task 4: Implement the local Git/GitHub Desktop adapter

**Files:**

- Add Git command and repository services under `tools/lore_editor/git_adapter.py`.
- Add API routes and tests for repository state and operations.

**Tests first:**

- [x] Test status parsing for clean, dirty, ahead, behind, diverged, and conflicted repositories. (2026-08-20: added `test_status_reports_clean_repository_with_no_pending_changes`, `test_status_reports_ahead_behind_and_diverged`, `test_status_reports_merge_conflicts` in `tools/lore_editor/tests/test_git_adapter.py`.)
- [ ] Test repository identity and allowed-path checks. (No repository-identity/allowed-path check exists in `git_adapter.py` yet to test against — needs the Implementation checkbox below done first.)
- [x] Test branch-name sanitization and branch creation in temporary repositories. (2026-08-20: added `test_create_branch_rejects_leading_dash_and_reflog_syntax` covering leading-dash and `@{` cases alongside the existing `..` case.)
- [ ] Test commit preview and explicit local commit behavior. (Explicit local commit is covered by existing `stage_and_commit` tests; no separate "commit preview" function exists yet to test.)
- [x] Test refusal when unrelated dirty files would be overwritten. (Covered by existing `test_stage_and_commit_leaves_preexisting_staged_unrelated_files_alone` and the new `test_stage_and_commit_rejects_absolute_and_escaping_paths` / `test_stage_and_commit_raises_when_requested_paths_have_no_staged_changes`.)
- [x] Test GitHub Desktop launcher discovery and missing-launcher guidance. (2026-08-20: added `test_open_in_github_desktop_raises_actionable_error_when_launcher_missing`.)

**Implementation:**

- [x] Detect `github.bat`, GitHub Desktop's bundled Git, and PATH fallback.
- [x] Serialize operations per repository and bound process output. (2026-08-20, implemented at the user's direction: added a per-resolved-repo-path `threading.Lock` registry (`_repo_lock()`) in `git_adapter.py`, held for the full duration of `repository_status`, `repository_revision`, `repository_remote_url`, `create_branch`, and `stage_and_commit` — not just each individual `_run_git` call — so a multi-step operation like `stage_and_commit`'s add+diff+commit can't interleave with a concurrent call against the same repo. Different repositories are not serialized against each other. Output bounding: `_run_git`'s error messages are truncated at 8,000 characters (`_truncate_output`), and `RepositoryStatus.changed_files`/`conflict_files` are capped at 2,000 entries with a new `truncated_change_count` field reporting the overflow. `open_in_github_desktop` was deliberately left unlocked — it only launches a detached GUI process and doesn't touch the working tree or index, so serializing it would just block unrelated status/commit calls for no correctness benefit. Tests: `test_operations_against_the_same_repository_are_serialized` and `test_operations_against_different_repositories_are_not_serialized` (both prove serialization via an instrumented `_run_git` tracking peak concurrent calls across 5 threads), `test_truncate_output_bounds_long_text`, `test_status_caps_changed_file_list_and_reports_truncated_count` in `test_git_adapter.py`.)
- [x] Add status, branch, commit, and open-in-Desktop actions.
- [x] Add visible UI state for branch, dirty files, conflicts, and required handoff actions.

## Task 5: Build first-run launcher and runtime bootstrap

**Files:**

- Add `Launch Lore Tools.cmd`.
- Add launcher/bootstrap code below `tools/launcher/`.
- Add setup and launch tests.

**Tests first:**

- [x] Test compatible system Python detection. (2026-08-20: verified live — ran `tools/launcher/launch.ps1` end-to-end twice this session; both times it found the system Python via `Find-CompatiblePython` and used it without triggering a download.)
- [ ] Test declined runtime download produces actionable guidance. (Code-inspection only — `Show-RequirementsGuidance` + `exit 1` on a "no" answer — not exercised live, since this machine already has compatible Python so the download prompt never triggers.)
- [ ] Test runtime download checksum failure leaves no active runtime. (Not exercised — would require deliberately serving a corrupted installer or a signature mismatch; not attempted without a reason to modify `runtime_manifest.json` or intercept the download.)
- [x] Test cached runtime reuse and server/browser startup command construction. (2026-08-20: verified live twice, including once after fixing the `ConvertTo-EscapedArgument` argument-quoting bug — the server started, printed `LORE_EDITOR_URL=`, and the browser-open call fired both times.)
- [x] Test first-run settings persistence outside the repository. (2026-08-20: confirmed `%LOCALAPPDATA%\AphelionLoreTools\settings.json` exists with the persisted `gameRepository` path from a prior run, and `Read-GameRepository`'s "use the nearby checkout" default-yes prompt was exercised live in both launcher runs this session.)

**Implementation:**

- [x] Prompt before downloading the pinned runtime.
- [x] Download atomically into `%LOCALAPPDATA%\\AphelionLoreTools\\runtime`.
- [x] Store only runtime version, paths, and preferences in per-user settings.
- [x] Start the loopback server and open the browser automatically.
- [x] Add first-run game-checkout selection and validation.
- [x] Ensure direct `file:` opening displays guidance rather than a broken loading state.

## Task 6: Port and expand the browser workflow

**Files:**

- Port `app.js`, `index.html`, and `styles.css` under the standalone web package.
- Add configuration, Git status, staging, export, and conflict panels.

**Tests first:**

- [x] Test startup health and catalog loading through a live local server. (2026-08-20: added `test_server_reports_health_and_serves_the_catalog_on_startup` in `tools/lore_editor/tests/test_standalone_server.py`.)
- [x] Test save conflict responses and reload/compare behavior. (2026-08-20: this refers to Git-status conflicts surfaced in the review workflow, not a separate optimistic-concurrency save mechanism — `save_entry`/`create_entry` have no revision-conflict check to test. Added `test_server_reports_git_conflict_status_through_the_api`, which drives a real merge conflict through `/api/git/status`.)
- [x] Test branch creation, commit confirmation, and GitHub Desktop handoff controls. (2026-08-20: branch creation was already covered; added `test_server_commit_endpoint_commits_requested_paths_and_reports_remaining_dirty_files` and `test_server_open_in_github_desktop_endpoint_reports_missing_launcher`.)
- [x] Test export preview, apply refusal, and successful apply states. (2026-08-20: the existing mocked test already covered the successful-apply HTTP contract; added `test_server_export_apply_endpoint_refuses_when_game_checkout_is_dirty`, which exercises real (unmocked) `prepare_export`/`apply_export` through the live HTTP endpoints.)
- [ ] Test keyboard navigation and usable loading/error states. (Not testable with the current stdlib-only test stack — no browser-automation dependency exists in this project. User decided (2026-08-20) to keep the test stack as unittest+urllib server-integration tests rather than add Playwright; this item is a known, accepted gap, not silently skipped.)

**Implementation:**

- [x] Replace game-repository-relative APIs with explicit tool-root/game-root services.
- [x] Preserve current search, groups, reviews, icon editor, and tool execution behavior. (2026-08-20: covered by the 149-test suite — including the search/filter caching fix, group and review round-trip tests, icon preview tests, and tool-run tests — plus live browser verification of search/filter this session.)
- [x] Add repository setup and status header.
- [x] Add native Git actions with confirmation and bounded output.
- [x] Add writer-friendly staged export flow and clear maintainer handoff.

## Task 7: Implement staged export and safe game-repository apply

**Files:**

- Add stage/export services, manifest handling, and CLI commands.
- Update generated DM metadata.
- Add integration fixtures for both repositories.

**Tests first:**

- [x] Test prepare-export does not modify the game checkout.
- [x] Test export manifest hashes and source/catalog provenance.
- [x] Test apply to a clean checkout.
- [x] Test refusal on stale game revision, changed generated artifact, dirty destination, and missing module. (2026-08-20: added `test_apply_export_refuses_when_game_revision_changed`, `test_apply_export_refuses_when_game_checkout_is_dirty`, `test_apply_export_refuses_when_game_module_is_missing` in `tools/lore_editor/tests/test_export.py`; the changed-artifact case was already covered.)
- [x] Test atomic rollback when writing or generation fails. (2026-08-20: added `test_prepare_export_removes_partial_stage_directory_on_failure`, which injects a failure into the second `_atomic_write` call and confirms the partial stage directory is removed.)

**Implementation:**

- [x] Add `prepare-export`, `apply-export`, and export preview commands.
- [x] Generate only the runtime DM artifact for the game repository.
- [ ] Create a game branch and local commit only after explicit confirmation. (Investigated 2026-08-20: confirmed unimplemented — `apply_export` only writes the artifact file; it never brances or commits. Today the writer is expected to do this manually via the Meridian-Rift repository panel after a successful apply, which [writer-guide.md](../writer-guide.md) documents as the current behavior. Auto-branch/commit is a real product feature, not a bug, and needs a decision on the commit message and whether it's automatic or a separate confirm step before building it.)
- [x] Open the game checkout in GitHub Desktop after successful apply. (2026-08-20, implemented at the user's direction: `/api/export/apply` in `server.py` now calls `open_in_github_desktop(game_repo_root)` automatically after a successful apply, as a best-effort follow-up — if it fails (e.g. launcher not found), the response still reports `"applied": true` with `"opened_in_github_desktop": false` and a `"github_desktop_error"` message, since the artifact write itself already succeeded and must not be reported as failed over a convenience step. `app.js` surfaces the outcome in the export-output message. Tests: `test_server_export_apply_endpoint_opens_github_desktop_for_the_game_checkout_on_success` (mocks the launcher and `subprocess.Popen`, asserts the exact command) and an added assertion on the existing `test_server_exposes_prepare_and_apply_export_actions` for the failure case (no game checkout directory).)

## Task 8: Update Meridian-Rift integration

**Files:**

- Update `tools/build/build.ts`.
- Update `.github/workflows/autowiki.yml`.
- Update the lore-overhaul module README and generated artifact header.
- Remove or replace migrated editor/source paths only after import verification.

**Tests first:**

- [x] Run standalone validation and export tests against the migrated corpus. (2026-08-20: `python tools/lore_editor/cli.py validate --repo-root . --check-generated` passes; full standalone suite is 149/149.)
- [x] Compile the imported generated DM in Meridian-Rift. (2026-08-20: BYOND was found installed at `C:\Program Files (x86)\BYOND` (not on PATH). Ran `dm.exe tgstation.dme` directly: `tgstation.dmb - 0 errors, 3 warnings`, exit code 0 — matches the prior session's result exactly. Build artifacts cleaned up afterward; `git status` unaffected.)
- [x] Run AutoWiki build generation with the imported artifact. (2026-08-20: ran `tools\build\build.bat --ci autowiki` — the same command the `autowiki.yml` CI workflow runs. The AUTOWIKI-mode compile succeeded (0 errors, 0 warnings), the game booted to full initialization with zero lore_overhaul-related errors in `runtime.log`, and `data/autowiki_edits.txt` was produced with real content (493.8KB, other autowiki types like fish entries present) but correctly contains no lore_overhaul pages — the only current override (`ashtongue` language) has no `wiki` field set, so `wiki.enabled` is `False` and the generator correctly emits no registry/autowiki blocks for it (verified in `generate.py`'s `iter_registry_entries`/`render_autowiki_block`). The Juke build step itself reported failure (`exit code: 144`) — traced to `dreamdaemon.exe -close`'s own Windows shutdown exit code, which this CI tooling (written for the `ubuntu-24.04` GitHub Actions runner) doesn't special-case; `tools/build/lib/byond.ts`'s `DreamDaemon()` just forwards whatever `Juke.exec` returns. This is a pre-existing Windows-local tooling quirk, not a lore_overhaul regression — the actual game and AutoWiki logic both completed cleanly. Test artifacts (`data/logs/ci`, `data/autowiki_edits.txt`, `data/autowiki_files`, `tgstation.test.*`, `tgstation.dmb`) were removed afterward; `git status` confirmed unaffected.)
- [x] Confirm unrelated existing game-repository changes remain present. (2026-08-20: `git status --short` in Meridian-Rift still shows exactly the 5 expected changed files — `.gitignore`, `code/modules/autowiki/autowiki.dm`, `tgstation.dme`, `tools/build/build.ts`, plus the untracked `modular_aphelion/modules/lore_overhaul/` — untouched since the last pause.)

**Implementation:**

- [x] Stop game-repo build targets from expecting the standalone editor/source tree. (2026-08-20, verified by inspection: `tools/build/build.ts` only adds `modular_aphelion/**` to the DreamMaker watch globs — it doesn't reference the standalone tool's `tools/lore_editor` or `config/aphelion/lore_overhaul` paths at all, and a repo-wide search for `lore_editor`/old editor references in Meridian-Rift turns up nothing outside a comment in the generated artifact.)
- [x] Keep runtime module includes and generated DM compilation intact. (2026-08-20, verified by inspection: `tgstation.dme` includes exactly the 5 expected files — `catalog_probe.dm`, `lore_entry.dm`, `autowiki.dm`, `autowiki_tests.dm`, `generated_lore_overrides.dm` — under `modular_aphelion/modules/lore_overhaul/code/`.)
- [x] Keep AutoWiki publication CI-only. (2026-08-20, verified by inspection: `.github/workflows/autowiki.yml` has no diff from upstream — still `schedule`/`workflow_dispatch`-only, still gated on the `AUTOWIKI_USERNAME` secret being set. `autowiki.dm`'s only change is skipping the abstract `/datum/autowiki/lore_overhaul` base type so only its generated subtypes publish pages.)
- [x] Document the standalone-to-game-repo handoff. (2026-08-20: [maintainer-guide.md](../maintainer-guide.md)'s "Staged export mechanism" and "Game-repository build integration" sections; see Task 9.)

## Task 9: Documentation and release packaging

**Files:**

- Add writer guide and maintainer guide under `references/`.
- Update root README with the double-click workflow. (done)
- Add release/bootstrap instructions under `tools/launcher/`. (done)

**Tests first:**

- [x] Follow the clean-machine launch instructions from a fresh checkout. (2026-08-20: ran `tools/launcher/launch.ps1 -RepositoryRoot <repo>` directly, the same entry point `Launch Lore Tools.cmd` invokes. It found the system Python, resolved the game-repository prompt gracefully with no answer available (this shell has no stdin, matching the documented "blank to continue without it" path), started the server, and printed the `LORE_EDITOR_URL=` line. This exercised the "compatible Python already installed" branch, not a truly Python-free machine.)
- [ ] Test accepted and declined runtime bootstrap paths. (Declined path verified by code inspection only — `Show-RequirementsGuidance` + `exit 1` when the download prompt is answered no. Neither path was exercised live this session: this machine already has compatible Python, and the accepted path would download and run a real installer, which wasn't done without a reason to.)
- [ ] Test setup with both repositories already registered in GitHub Desktop. (Not verifiable from this tool session — depends on GitHub Desktop's own local repository list, which isn't something a Python/PowerShell check can exercise.)

**Implementation:**

- [x] Document the only required user software and repository setup. (2026-08-20: [writer-guide.md](../writer-guide.md) "First run" section, backed by the existing README.)
- [x] Document normal writer, conflict, export, and maintainer workflows. (2026-08-20: [writer-guide.md](../writer-guide.md) covers writer/conflict/export; [maintainer-guide.md](../maintainer-guide.md) covers maintainer-specific tasks.)
- [x] Document recovery for dirty repositories, stale catalogs, and failed exports. (2026-08-20: writer-guide.md's export-refusal table and stale-catalog note.)
- [x] Keep internal implementation details out of the root end-user README. (README unchanged this session — still writer-facing only; the new maintainer-level detail lives in `references/maintainer-guide.md` instead.)

## Task 10: Final verification and review

- [x] Run standalone unit and integration tests. (2026-08-20: 149/149 pass — `python -m unittest discover -s tools/lore_editor/tests -p 'test_*.py'`.)
- [x] Run JavaScript syntax checks and browser smoke tests. (2026-08-20: `node --check tools/lore_editor/web/app.js` clean; live browser smoke test confirmed catalog load, search/filter, and the launcher's real browser-open flow.)
- [x] Run migration idempotence checks. (2026-08-20: ran `cli.py generate` twice in a row against the real repo — byte-identical SHA-256 output both times, confirming deterministic generation. Existing unit tests separately cover deterministic ordering/hashing for catalog manifests, entry lists, and validation-issue ordering.)
- [x] Run `git diff --check` in both repositories. (2026-08-20: clean in both `aphelion-lore-tools` and `Meridian-Rift`.)
- [x] Compile Meridian-Rift with PowerShell and inspect `$LASTEXITCODE`. (2026-08-20: `tgstation.dmb - 0 errors, 3 warnings`, `$LASTEXITCODE` 0. See Task 8 for detail.)
- [x] Run the AutoWiki build gate. (2026-08-20: ran and inspected in detail — see Task 8. Game and AutoWiki logic both completed cleanly; the build tool's own exit code (144) is a pre-existing Windows/DreamDaemon quirk in this CI tooling, unrelated to the lore_overhaul changes.)
- [x] Perform a full code review for path traversal, credential exposure, destructive Git behavior,
  stale-catalog handling, conflict safety, and Windows launch failures. (2026-08-20 — see findings below.)
- [x] Leave all changes uncommitted unless explicitly requested. (Confirmed: both repositories still show only their pre-existing pending changes; nothing was committed or pushed.)

### Code review findings (2026-08-20)

- **Path traversal:** every user/query-influenced path resolver (`icon_preview._resolve_icon_path` and `_approved_icon_root`, `api._resolve_entity_source`, `export._resolve_child`, `git_adapter.stage_and_commit`'s path validation, `server.export_stage_path`) rejects absolute input and re-checks `is_relative_to()` against an explicit allowed root after resolution. No gaps found.
- **Credential exposure:** no code path reads, stores, transmits, or logs a password, token, or credential anywhere in `tools/`; the only hits for those keywords are unrelated in-game item names in `targets.json`. GitHub Desktop is only ever launched as a subprocess with a directory argument, per the "app must never receive or store GitHub credentials" constraint.
- **Destructive Git behavior:** no `reset --hard`, `clean -f`, `push --force`, or hook-bypass flags exist anywhere in the codebase. `create_branch` uses `switch --create` (never overwrites), `stage_and_commit` uses `commit --only` scoped to explicit paths.
- **Stale-catalog handling:** the new `_review_entries_snapshot` cache (see the search-latency fix above) is invalidated by content file stamps, not time — confirmed by `test_repeated_queries_reuse_the_cached_review_snapshot`. The catalog snapshot itself only goes stale relative to the game repo when a writer hasn't run "Refresh catalog" after a game-side content change; this is an intended, documented manual step, not a caching bug.
- **Conflict safety:** `apply_export` refuses on both `status.conflicted` and `status.dirty` before touching the game checkout (tested); Git-status conflict detection is unit-tested against a real merge conflict at both the adapter and HTTP-endpoint levels.
- **Windows launch failures — one real finding, fixed:** [tools/launcher/launch.ps1](../../tools/launcher/launch.ps1) built the child process's `Arguments` string with a naive `'"' + $_.Replace('"', '\"') + '"'` quoting scheme. Per Windows' `CommandLineToArgvW` argument-parsing rules, a trailing backslash immediately before a closing quote is not escaped by that scheme, so an argument ending in `\` (e.g. a repository checked out at a drive root like `C:\`) would corrupt the argument boundary and could crash or misdirect the launch. Replaced with a `ConvertTo-EscapedArgument` helper implementing the standard backslash-doubling algorithm, and round-trip verified it against Python's own argv parser for trailing-backslash, embedded-quote, and space-containing inputs — all now round-trip exactly. Re-ran the full launcher end-to-end afterward to confirm the common case (a normal repository path) still works.
