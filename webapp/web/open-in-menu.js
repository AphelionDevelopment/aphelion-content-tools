(() => {
  'use strict';

  // Shared "Open in..." action menu -- used by Content Graph (node detail panel) and Lore Editor (entry
  // detail panel), which previously reimplemented the same three actions as two different, both slightly
  // broken UI patterns (a dropdown that grew the scrollable panel it lived in; a row of three always-
  // visible buttons). One component now owns both the actions and a correctly-floating menu, positioned
  // with the vendored Floating UI (see /floating-ui-core.umd.min.js, /floating-ui-dom.umd.min.js) so it's
  // never clipped by -- or forced to extend -- a scrolling ancestor's overflow, the root cause of the
  // original bug: a `position: absolute` dropdown still contributes to its scrolling ancestor's
  // scrollable content box, it doesn't float free of it.

  async function requestJson(path, options = {}) {
    const response = await fetch(path, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : {};
    if (!response.ok) throw new Error(payload.error || ('Request failed (' + response.status + ')'));
    return payload;
  }

  async function openInGithub(repository, path, line) {
    const payload = await requestJson('/api/git/github-url?repository=' + encodeURIComponent(repository) + '&path=' + encodeURIComponent(path));
    if (!payload.url) throw new Error('No GitHub remote is configured for this repository.');
    window.open(payload.url + (line ? '#L' + line : ''), '_blank', 'noopener');
  }

  async function openInEditor(repository, path) {
    await requestJson('/api/git/open-file', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({repository, path, target: 'editor'}),
    });
  }

  async function revealInExplorer(repository, path) {
    await requestJson('/api/git/open-file', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({repository, path, target: 'explorer'}),
    });
  }

  let openMenuState = null; // {menu, cleanupAutoUpdate} for whichever menu is currently open, or null

  function closeOpenMenu() {
    if (!openMenuState) return;
    openMenuState.cleanupAutoUpdate();
    openMenuState.menu.remove();
    openMenuState = null;
  }

  document.addEventListener('click', closeOpenMenu);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeOpenMenu();
  });

  // Renders a compact "Open in..." toggle into `container`; the menu itself is portaled to <body> and
  // positioned relative to the toggle via Floating UI, so it's never a descendant of (and therefore
  // never contributes to the scrollable content size of) whatever scrolling panel `container` lives in.
  function render(container, {repository, path, line, onError}) {
    const reportError = onError || ((message) => console.error(message));
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'secondary-button open-in-toggle';
    toggle.textContent = 'Open in…';

    toggle.addEventListener('click', (event) => {
      event.stopPropagation();
      const alreadyOpenForThisToggle = openMenuState && openMenuState.toggle === toggle;
      closeOpenMenu();
      if (alreadyOpenForThisToggle) return;

      const menu = document.createElement('div');
      menu.className = 'open-in-list';
      const options = [
        ['Local Explorer', () => revealInExplorer(repository, path)],
        ['Local Editor', () => openInEditor(repository, path)],
        ['GitHub Web', () => openInGithub(repository, path, line)],
      ];
      for (const [label, action] of options) {
        const item = document.createElement('button');
        item.type = 'button';
        item.textContent = label;
        item.addEventListener('click', (itemEvent) => {
          itemEvent.stopPropagation();
          closeOpenMenu();
          action().catch((error) => reportError(error.message));
        });
        menu.append(item);
      }
      menu.addEventListener('click', (menuEvent) => menuEvent.stopPropagation());
      document.body.appendChild(menu);

      const {computePosition, autoUpdate, offset, flip, shift} = window.FloatingUIDOM;
      function updatePosition() {
        computePosition(toggle, menu, {
          strategy: 'fixed', // viewport-relative -- immune to any scrolling ancestor, not just this one
          placement: 'bottom-start',
          middleware: [offset(4), flip(), shift({padding: 8})],
        }).then(({x, y}) => {
          menu.style.left = x + 'px';
          menu.style.top = y + 'px';
        });
      }
      const cleanupAutoUpdate = autoUpdate(toggle, menu, updatePosition);
      openMenuState = {toggle, menu, cleanupAutoUpdate};
    });

    container.append(toggle);
  }

  const api = {render, openInGithub, openInEditor, revealInExplorer};
  window.AphelionOpenInMenu = api;

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
