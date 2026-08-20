# Aphelion Content Tools

Windows-first browser tools for authoring, maintaining, and understanding modular Aphelion/Nova
content outside the Meridian-Rift game repository. Currently includes **Home** (repository status,
local Git actions, and cache/storage management shared across every tool), the **Lore Editor** (catalog
review, writer groups, overrides, staged export), and the **Content Graph** (a visual map of
`modular_nova`/`modular_aphelion` modules, `master_files` overrides, and `NOVA EDIT`/`APHELION EDIT`
markers). Use the pills at the top of the page to switch between tools; Home carries its own accent
color to set it apart from the tool pages.

## Start here

1. Open this repository in GitHub Desktop and sign in.
2. Make sure your local `Meridian-Rift` checkout is available beside this repository, or have its full path ready.
3. Double-click [Launch Aphelion Content Tools.cmd](Launch%20Aphelion%20Content%20Tools.cmd).
4. The launcher opens the app in your browser and remembers the game-checkout path for later launches.

If Python 3.11+ with Pillow is already installed, the launcher uses it. Otherwise it asks before downloading a private per-user Python runtime. Declining leaves installation instructions and does not change the machine. GitHub Desktop remains responsible for sign-in, pushing, pull requests, and complicated merge conflicts.

## Home

The landing page (`/`). Use the repository panel to create a local branch, commit selected repository
changes, and open the relevant checkout in GitHub Desktop. Use **Cache and Storage Management** to run
catalog refresh, validation, generation, and content-graph scan jobs without leaving this page — it
lists every tool's registered job, not just one tool's.

## Lore Editor

Use the catalog search and groups to find targets, mark current content as reviewed, or create a
per-record override.

For a game change, use **Prepare export** first. Review the manifest, then apply it only to a clean, unchanged game checkout. The app writes only `modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm`; it refuses stale revisions, conflicts, dirty checkouts, and unexpected artifact changes.

## Content Graph

Open **Content Graph** and click **Scan modular content** to index the selected game checkout's modules, `master_files` overrides, and inline edit markers into a cached graph. Re-run the scan after the game checkout changes — it isn't automatic. Markers whose module attribution can't be confirmed against a real module directory appear in the Unresolved markers list rather than as graph edges, since most existing markers only carry a free-text reason, not a clean module id.

## Repository layout

- `webapp/` — the shared app shell: local HTTP server, Git integration, background job runner, and the Home page (`/`) shared by every tool.
- `tools/lore_editor/` — the Lore Editor tool (`/lore-editor`): content, catalog snapshot, and domain logic.
- `tools/content_graph/` — the Content Graph tool: scanner, marker parser, and its page.
- `references/` — maintainer and architecture documentation.
- `Launch Aphelion Content Tools.cmd` — the only launcher most writers need.

Each tool's content directory is the source of truth for its own data. The game repository only receives generated artifacts (e.g. the lore override DM) through explicit export workflows; never hand-edit a generated file.
