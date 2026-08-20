# Aphelion Lore Tools

Windows-first browser tools for maintaining Aphelion lore overrides outside the Meridian-Rift game repository.

## Start here

1. Open this repository in GitHub Desktop and sign in.
2. Make sure your local `Meridian-Rift` checkout is available beside this repository, or have its full path ready.
3. Double-click [Launch Lore Tools.cmd](Launch%20Lore%20Tools.cmd).
4. The launcher opens the local editor in your browser and remembers the game-checkout path for later launches.

If Python 3.11+ with Pillow is already installed, the launcher uses it. Otherwise it asks before downloading a private per-user Python runtime. Declining leaves installation instructions and does not change the machine. GitHub Desktop remains responsible for sign-in, pushing, pull requests, and complicated merge conflicts.

## Writer workflow

Use the catalog search and groups to find targets, mark current content as reviewed, or create a per-record override. Use the Tools panel for catalog refresh, validation, and generation. Use the repository panel to create a local branch, commit selected repository changes, and open the relevant checkout in GitHub Desktop.

For a game change, use **Prepare export** first. Review the manifest, then apply it only to a clean, unchanged game checkout. The app writes only `modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm`; it refuses stale revisions, conflicts, dirty checkouts, and unexpected artifact changes.

## Repository layout

- `tools/lore_editor/content/` — per-record overrides, groups, reviews, and assignments.
- `tools/lore_editor/catalog/` — committed catalog snapshot and provenance manifest.
- `tools/lore_editor/web/` — the local browser interface.
- `references/` — maintainer and architecture documentation.
- `Launch Lore Tools.cmd` — the only launcher most writers need.

The standalone repository is the source of truth. The game repository receives the generated modular Aphelion DM artifact through the explicit export workflow; writers should not edit generated DM by hand.
