# Standalone Lore Tools Migration Handoff

Status: the full plan in `standalone-migration-plan.md` has been worked through as of 2026-08-20, including a live BYOND compile and AutoWiki build gate in Meridian-Rift (BYOND is installed there at `C:\Program Files (x86)\BYOND`, not on PATH). Changes are intentionally left uncommitted and unpushed in both repositories. What's genuinely still open is a short list of unimplemented features (each needing a product decision, not a bug fix) and untestable-in-this-environment items — see the plan document's per-item notes for specifics.

## Current repositories

- Tool repository: `C:\Users\Zoe\Documents\GitHub\aphelion-lore-tools`
- Game repository: `C:\Users\Zoe\Documents\GitHub\Meridian-Rift`
- The tool repository is now the source of truth for catalog snapshots, writer groups, reviews, assignments, and per-record overrides.
- The game repository keeps only the runtime `modular_aphelion/modules/lore_overhaul` code and generated DM artifact.

## Implemented

- Standalone Windows launcher: `Launch Lore Tools.cmd` and `tools/launcher/launch.ps1`.
- Compatible Python discovery, consent-gated per-user Python installation, Pillow dependency setup, game-repository selection, loopback server launch, and browser opening.
- Standalone per-record JSON content under `tools/lore_editor/content/`.
- Catalog refresh against a separately selected game checkout; current real snapshot contains 20,881 targets.
- Configurable groups, keyword/type-path matching, reviewed state, attention state, overrides, directional/redundant visibility controls, sorting, and search.
- Icon metadata and preview endpoints using the selected game repository.
- Native local Git status, branch creation, scoped commit, and GitHub Desktop opening. Pushes, pull requests, and complex merges remain in GitHub Desktop.
- Staged export workflow: prepare outside the game checkout, review the manifest, then apply only to a clean compatible game checkout.
- Export safeguards for dirty checkouts, changed revisions, changed generated artifacts, missing module paths, invalid manifests, and conflicts.
- Build integration removed the old in-game editor/catalog target. AutoWiki now consumes the normal generated runtime artifact.
- Documentation updated in the root README and `references/architecture/`.

## Verification already completed

- `python -m unittest discover -s tools/lore_editor/tests -p 'test_*.py'`: 129 tests passed before the final browser-only inspection.
- `node --check tools/lore_editor/web/app.js`: passed.
- PowerShell parser check for `tools/launcher/launch.ps1`: passed before the last launcher manifest adjustment; rerun before calling the work complete.
- `python tools/lore_editor/cli.py generate --repo-root .`: passed.
- `python tools/lore_editor/cli.py validate --repo-root . --check-generated`: passed.
- Live API smoke: health, catalog, review, Git status, stages, and icon listing all returned successfully.
- DreamMaker compile in a normal Windows context: `tgstation.dmb - 0 errors, 3 warnings`; exit code 0. The warnings are the existing BUILD.cmd-mode warnings.
- A real export stage was prepared successfully at:
  `tools/lore_editor/stages/20260820T143644Z-70de7d89afa5`
- Applying that stage was intentionally refused because the game checkout had pre-existing uncommitted changes. No game file was modified by the refused apply.
- `git diff --check` passed in both repositories.

## Last browser observation (2026-08-20, post-latency-fix)

- The loopback page loads successfully and initially displays `Loading catalog…` while the 20k-target catalog is fetched.
- After loading, it displays 13,175 visible targets and the configured groups.
- Search input is clickable and accepts text. Searching for `Nanotrasen` now updates the count (330 matches) and re-renders the list within tens of milliseconds after the debounce — the multi-second refresh delay is resolved (see "Search/filter latency fix" below).
- The visible repository workflow and review layout were inspected at desktop width and were usable; no additional CSS change was made after that inspection.

## Search/filter latency fix (2026-08-20)

- Root cause (found by investigation agent, confirmed by profiling): `list_review_response` in `tools/lore_editor/api.py` rebuilt, decorated, filtered, and sorted all ~20,881 catalog targets from scratch on every `/api/review` request — including re-running `thaw_json` per target and re-reading reviews/groups from disk — before truncating to the 500-row page. Client-side debouncing (150ms) and request cancellation (`AbortController`) were already correctly implemented; the bottleneck was entirely server-side CPU work per keystroke.
- Fix: added `_review_entries_snapshot`/`_build_review_entries_snapshot` in `tools/lore_editor/api.py`, which caches the fully decorated (pre-filter, pre-sort) entry list, status/group counts, and issues in-memory, keyed by file stamps of targets/groups/assignments/reviews/overrides (same pattern as the existing `_review_catalog_index` cache). Per-request work for a query/filter/sort change now only filters, sorts, and slices the cached list — no re-decoration, re-thaw, or disk re-reads. The 500-row response cap is unchanged.
- Verified: added `test_repeated_queries_reuse_the_cached_review_snapshot` in `tools/lore_editor/tests/test_review_api.py` (132 tests pass). Benchmarked against the real 20,881-target catalog: cold snapshot build ~2.7s (once, on first request after any content change), subsequent filtered/sorted requests ~60-80ms. Confirmed live in-browser: typing "Nanotrasen" into the search box now updates the result count (330 matches) and list within the debounce window.
- Note: the full `/api/catalog` fetch on page load (`loadEditorData()` in `app.js`) still serializes all 20,881 targets just to read one boolean flag (`state.standalone`). This is a separate, smaller inefficiency (page-load only, not per-keystroke) and was not addressed here — worth a follow-up if initial load time becomes a concern.

## Recommended next session plan

1. ~~Re-run the full standalone tests, JavaScript syntax check, launcher PowerShell parse check, and JSON/schema validation after the latest changes.~~ Done (2026-08-20): 132 tests pass, JS syntax clean, launcher parses, `validate --check-generated` passes, `git diff --check` clean.
2. ~~Add timing instrumentation around the browser's catalog refresh request and the server's list/review path.~~ Done via investigation agent + profiling — see "Search/filter latency fix" above.
3. ~~Improve search/filter responsiveness without changing the source-of-truth model.~~ Done — see "Search/filter latency fix" above.
4. ~~Add browser-level regression coverage~~ Done as far as the current stack allows (2026-08-20): the user chose to extend the existing unittest+urllib server-integration pattern rather than add a browser-automation dependency (e.g. Playwright). Added 5 tests to `tools/lore_editor/tests/test_standalone_server.py` covering health/catalog startup, Git conflict status through `/api/git/status`, the commit endpoint, GitHub Desktop's missing-launcher error, and export-apply refusal on a dirty game checkout via real (unmocked) `prepare_export`/`apply_export`. Genuinely not coverable without real browser automation: keyboard navigation and DOM-level loading/error-state rendering — flagged as an accepted gap, not silently skipped. Search text, group checkboxes, and entry selection were separately verified live in-browser this session (see "Search/filter latency fix" above) but are not automated regression tests.
5. ~~Add export tests for stale tool revision, stale game revision, dirty game checkout, missing module, changed generated artifact, and successful apply in an isolated clean fixture.~~ Done (2026-08-20): added `test_apply_export_refuses_when_game_revision_changed`, `test_apply_export_refuses_when_game_checkout_is_dirty`, `test_apply_export_refuses_when_game_module_is_missing`, `test_prepare_export_removes_partial_stage_directory_on_failure` to `tools/lore_editor/tests/test_export.py`. (Stale *tool* revision specifically was not added — the export manifest does not currently gate on tool-repo revision drift, only game-repo revision and artifact hash; flagged as a possible gap, not a test gap.)
6. Re-run the game-repository AutoWiki/build gate after the final standalone changes.
7. Complete the requested full code review, update the migration plan checkboxes, and report any remaining untested gates explicitly.
8. Optional follow-up: avoid the full-catalog `/api/catalog` fetch on page load if initial load latency becomes a concern (see note above).

## Launch Lore Tools.cmd argument-quoting bug (2026-08-20)

The user hit `Resolve-Path : Illegal characters in path` on double-clicking `Launch Lore Tools.cmd`.
Root cause: `%~dp0` always expands with a trailing backslash, and line 3's
`-RepositoryRoot "%~dp0"` quoted it bare — the trailing `\"` is misparsed by Windows' standard
argument-escaping rule (an odd run of backslashes before a quote escapes the quote into a literal
character instead of closing the string), so PowerShell received the path with a stray `"` appended.
This is the exact same class of bug as the `launch.ps1` argument-escaping fix from earlier in this
session, but in a different, untested spot — the .cmd file's own invocation of PowerShell, which my
earlier "Windows launch failures" review missed because I only ever tested `launch.ps1` directly
(`powershell.exe -File launch.ps1 -RepositoryRoot <path>`), never through the actual `.cmd` double-click
entry point where `%~dp0`'s trailing backslash is what triggers it.

Fixed by changing `"%~dp0"` to `"%~dp0."` — the quoted string now ends in `.` instead of a bare
backslash, sidestepping the escape hazard entirely (`\.` is a harmless no-op path segment that
`Resolve-Path` normalizes away). Reproduced the exact reported error against real `cmd.exe` argument
parsing before fixing, and confirmed the fix resolves correctly, both via direct simulation and by
actually running `Launch Lore Tools.cmd` end-to-end (all of `cmd.exe` → `powershell.exe` → `python.exe`
started cleanly). Added `tools/lore_editor/tests/test_launcher_cmd.py` as an automated regression
guard — it runs the real `cmd.exe` against the shipped `.cmd` file's actual content (with a stub
`launch.ps1` standing in so it doesn't need to start a real server), and was verified to fail against
the old broken line and pass against the fix.

## Additional Git-adapter test coverage (2026-08-20)

Also closed most of Task 4's outstanding test checkboxes in `tools/lore_editor/tests/test_git_adapter.py`: clean-repository status, ahead/behind/diverged status (via a bare-repo + two-clone fixture), an actual merge-conflict scenario, additional unsafe branch-name cases (leading dash, `@{`), commit-path validation (absolute paths, path escaping, no-op commits), and GitHub Desktop's missing-launcher error message. Two Task 4 checklist items remain genuinely open because the underlying feature doesn't exist yet, not because tests are missing: "repository identity and allowed-path checks" and "commit preview" have no corresponding implementation to test. Full suite is now 144 tests (was 129 at the last pause), all passing.

## Important workflow constraints

- Do not commit or push without explicit authorization.
- Preserve the existing dirty changes in `Meridian-Rift`.
- Keep new runtime content in `modular_aphelion`.
- Keep contributor-facing edits in the standalone tool repository; do not reintroduce the old game-repository editor/catalog structure.
- Browser use must not handle GitHub credentials or wiki credentials.
