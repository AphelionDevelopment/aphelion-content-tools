# Aphelion Lore Tools Standalone Migration Design

## Status

Approved design. Implementation is intentionally not included in this document.

## Decision summary

`aphelion-lore-tools` becomes the canonical home for lore-writer content and the local browser editor.
`Meridian-Rift` receives only an explicitly prepared, validated runtime export. The tool is Windows-first
and is launched by double-clicking a repository launcher. GitHub Desktop remains the authentication and
remote Git client; the local tool provides safe local workflow controls and opens GitHub Desktop for
push, pull-request, and conflict resolution.

## Goals

- Let a non-programmer edit lore content without opening a terminal or editing DM.
- Keep writer-owned overrides, groups, reviews, and catalog metadata outside the game repository.
- Let the app create branches, show status and diffs, commit local work, prepare exports, and open the
  correct repository in GitHub Desktop.
- Require only GitHub Desktop, the two repositories, and an optional user-approved runtime bootstrap.
- Make simultaneous work safe through Git-friendly files and optimistic conflict detection.
- Preserve the existing generated DM and AutoWiki runtime contract.
- Keep the standalone repository root focused on launcher, references, and tools.

## Non-goals

- No hosted database or real-time collaborative editor in the first release.
- No GitHub token, GitHub API integration, GitHub CLI, or browser-side credential handling.
- No automatic force-push, merge, conflict discard, or destructive game-repository rewrite.
- No cross-platform launcher in the first release.
- No requirement for contributors to install Python manually.

## Repository boundaries

The standalone repository will expose this small root surface:

```text
Launch Lore Tools.cmd
README.md
LICENSE
references/
tools/
```

Implementation, tests, schemas, catalog data, and local workflow state live below `tools/`. Writer and
maintainer documentation live below `references/`. Temporary stages, logs, runtime downloads, and saved
paths are excluded from Git and live below `%LOCALAPPDATA%\\AphelionLoreTools` where practical.

The planned internal layout is:

```text
tools/
  launcher/
    launch.ps1
    runtime_manifest.json
  lore_editor/
    app/
    catalog/
      targets.json
      manifest.json
    content/
      overrides/
      groups/
      reviews/
      assignments/
    schemas/
    stages/
    tests/
    web/
```

`tools/lore_editor/stages/` is local staging state and is ignored unless a future export policy makes a
manifest intentionally shareable. Canonical writer content is the per-record JSON below
`tools/lore_editor/content/`.

## Catalog and game checkout

The editor accepts a configured local `Meridian-Rift` path. The game checkout is used for:

- BYOND catalog probe compilation and execution.
- DMI icon files and state validation.
- Export provenance and target-revision checks.

The standalone repository stores a committed catalog snapshot so normal browsing and editing work without
the game checkout. A catalog manifest records the snapshot hash, game-repository revision, generation time,
target count, and format version.

Catalog refresh writes only the standalone snapshot. It may create ignored BYOND build/probe artifacts in
the selected game checkout, but it must not edit tracked game content. Refreshes are generated-data changes:
contributors do not manually merge target bodies. A stale snapshot is reported during export and must be
rebased or explicitly refreshed.

## Canonical content format

Each override, group, review, and manual assignment is stored in its own JSON file. Existing stable IDs are
preserved during migration. New override IDs are deterministic from the target type path, with a collision
suffix when necessary. The type path remains the target identity for runtime validation.

Per-record files are loaded into the same logical corpus currently used by the editor. The aggregate view is
generated in memory; no large grouped JSON file is rewritten when one writer changes one entry.

The editor uses atomic writes and records a content hash with each loaded editing session. A save that sees
a changed record returns a conflict instead of silently overwriting another writer's change.

## Native Git workflow

The local backend owns a narrow Git adapter. Every operation receives an explicit repository path, uses
argument arrays rather than shell command strings, serializes operations per repository, and returns bounded
stdout/stderr for the UI.

The app can:

- Detect GitHub Desktop's `github` launcher and bundled Git, falling back to a configured Git executable.
- Validate repository identity, remotes, current branch, upstream branch, and working-tree state.
- Fetch or fast-forward pull only when explicitly requested and safe.
- Create and switch to a lore branch using a predictable name.
- Show changed files, diffs, and conflict files.
- Commit local tool-repository changes after an explicit confirmation and commit-message review.
- Prepare and apply a game-repository export on a new branch.
- Open either repository at its current branch in GitHub Desktop.

The app will hand off push, pull-request creation, authentication prompts, and complex merge resolution to
GitHub Desktop. If the `github` launcher is unavailable, the app gives installation/configuration guidance
and still exposes the repository path for manual opening.

The app will refuse local operations that would overwrite uncommitted user changes outside its owned paths.
It will never run reset, clean, force-push, or an implicit merge.

## Launch and first-run experience

`Launch Lore Tools.cmd` performs these steps:

1. Resolve the standalone repository path.
2. Check for a compatible system Python installation.
3. If Python is unavailable, explain the requirement and ask whether to download the pinned runtime.
4. If accepted, download the verified runtime into `%LOCALAPPDATA%\\AphelionLoreTools\\runtime`, using a
   temporary file and checksum verification before activation.
5. If declined, show the supported Python requirement, installation guidance, and an option to retry.
6. Start the loopback server and open the application URL in the default browser.
7. Run the first-run setup flow if the game repository has not been configured.

The browser must never be opened directly from `file:`. The launcher owns server startup and browser
opening, and the app displays a clear health/error screen if the backend is unavailable.

The setup flow discovers likely sibling repositories and known GitHub Desktop repositories, then lets the
user confirm or select the game checkout. It stores only local paths and preferences, not credentials.

## Staging and game-repository export

The export pipeline has two explicit phases:

### Prepare export

Preparation runs complete content validation against the selected catalog and game checkout, generates the
DM artifact in a temporary location, and writes a local stage manifest containing:

- Tool-repository commit and branch.
- Catalog snapshot hash and source game revision.
- Targeted entry IDs and type paths.
- Generated artifact hash.
- Validation results and timestamp.

Preparation does not modify the game checkout.

### Apply export

Application requires the user to select a prepared stage and game checkout. It verifies the recorded game
repository revision and the expected current generated-artifact hash. It then writes only the generated
runtime artifact atomically, displays the exact diff, and offers to create a game-repository branch and
local commit. Any changed or conflicting destination causes a refusal with recovery guidance.

The generated DM header includes the source tool commit and catalog fingerprint so a game-repository PR can
be traced back to the standalone source.

## Concurrent editing and conflicts

- Different per-record files merge through Git without unnecessary content conflicts.
- Same-record saves use an optimistic content hash and return conflict data.
- Three-way merge can auto-merge changes to different fields of the same record.
- Changes to the same field produce a visible base/ours/theirs conflict requiring a writer decision.
- Group, review, and assignment records do not share a monolithic map file.
- A catalog change never silently invalidates an override; the UI identifies removed, changed, and new
  targets and export validation blocks unresolved stale-target conditions.
- A dirty game checkout is not modified unless all destination checks pass.
- A failed apply leaves both the stage and destination unchanged.

The app will show repository state prominently, including branch, ahead/behind status, dirty files,
stale-catalog warnings, pending conflicts, and the exact next GitHub Desktop action.

## Game-repository integration

The game repository keeps the static lore-overhaul runtime module and the generated DM artifact. The source
JSON, editor, catalog, groups, and review state move to the standalone repository.

Build integration will stop trying to validate or regenerate missing standalone source from inside the game
repository. Game-repository compilation and AutoWiki continue to compile the imported generated DM. The
standalone repository validates source and export consistency before the game-repository PR is created.

AutoWiki remains CI-only. The browser never receives wiki credentials and never publishes pages directly.

## Migration requirements

The migration must:

- Import the existing catalog, groups, reviews, and entity entries without changing their semantic values.
- Preserve existing IDs, type paths, special-description fields, icons, and AutoWiki records.
- Convert grouped entity arrays into one-record files deterministically.
- Produce byte-stable generated DM for equivalent content.
- Leave unrelated existing game-repository changes untouched.
- Update game-repository documentation and build references to describe the external source/export workflow.
- Retain a reversible import/export path during the transition.

## Acceptance criteria

- A clean Windows checkout launches by double-clicking the launcher and opens the app in a browser.
- A machine without Python receives a clear opt-in runtime download prompt and can continue without Python
  after accepting it.
- Declining the download shows actionable installation and retry guidance.
- A writer can select a target, edit it, validate it, create a branch, commit locally, and open the tool
  repository in GitHub Desktop without using a terminal.
- A maintainer can prepare an export, review its manifest and diff, apply it to a clean game checkout, create
  a local game branch/commit, and open that checkout in GitHub Desktop.
- Dirty or conflicting repositories are never overwritten.
- Two independent writer branches merge without unnecessary file conflicts.
- Same-entry conflicts are detected and surfaced.
- Catalog refresh and icon previews work with a configured game checkout.
- Standalone validation and export tests pass, and the imported generated DM compiles in Meridian-Rift.
