(() => {
  'use strict';

  const TOOL_ROUTES = {'/': 'home', '/file-management': 'file-management', '/lore-editor': 'lore-editor', '/graph': 'graph'};
  // A tool's own script, or an ordered array when it also needs vendored dependencies loaded first (see
  // Content Graph's UMD-global vendor files below) -- these live as <script> tags in the tool's own HTML
  // document, but sit outside <main class="shell">, so loadView's fetch-and-extract-<main> approach (used
  // when a tool is activated via the SPA nav rather than a hard page load) never picks them up on its own.
  // They have to be registered here explicitly and loaded in order before the tool's own script runs.
  const TOOL_SCRIPTS = {
    home: null,
    'file-management': '/file-management.js',
    'lore-editor': ['/floating-ui-core.umd.min.js', '/floating-ui-dom.umd.min.js', '/open-in-menu.js', '/lore-editor.js'],
    graph: [
      '/vendor/graphology.umd.min.js',
      '/vendor/sigma.min.js',
      '/vendor/d3-quadtree.v3.js',
      '/vendor/d3-dispatch.v3.js',
      '/vendor/d3-timer.v3.js',
      '/vendor/d3-force.v3.js',
      '/floating-ui-core.umd.min.js',
      '/floating-ui-dom.umd.min.js',
      '/open-in-menu.js',
      '/graph.js',
    ],
  };
  const TOOL_STYLES = {home: ['/styles.css'], 'file-management': ['/styles.css'], 'lore-editor': ['/styles.css'], graph: ['/styles.css', '/graph.css']};
  const TOOL_TITLES = {
    home: 'Aphelion Content Tools',
    'file-management': 'File Management — Aphelion Content Tools',
    'lore-editor': 'Lore Editor — Aphelion Content Tools',
    graph: 'Content Graph — Aphelion Content Tools',
  };

  const views = {};
  const loading = {};
  let activeTool = null;

  function toolFromPath(pathname) {
    return TOOL_ROUTES[pathname] || null;
  }

  function ensureProgressBar() {
    let bar = document.getElementById('shell-progress-bar');
    if (bar) return bar;
    const style = document.createElement('style');
    style.textContent =
      '#shell-progress-bar { position: fixed; top: 0; left: 0; right: 0; height: 3px; z-index: 1000; ' +
      'pointer-events: none; opacity: 0; transition: opacity .15s ease; overflow: hidden; }' +
      '#shell-progress-bar.is-active { opacity: 1; }' +
      '#shell-progress-bar .shell-progress-fill { position: absolute; top: 0; left: -40%; height: 100%; width: 40%; ' +
      'background: linear-gradient(90deg, transparent, #d16aff, #bb44f0, transparent); ' +
      'animation: shell-progress-sweep 1.1s ease-in-out infinite; }' +
      '@keyframes shell-progress-sweep { 0% { left: -40%; } 100% { left: 100%; } }';
    document.head.appendChild(style);
    bar = document.createElement('div');
    bar.id = 'shell-progress-bar';
    const fill = document.createElement('div');
    fill.className = 'shell-progress-fill';
    bar.appendChild(fill);
    document.body.appendChild(bar);
    return bar;
  }

  function setLoading(isLoading) {
    ensureProgressBar().classList.toggle('is-active', isLoading);
  }

  function dispatchVisibility(tool, visible) {
    window.dispatchEvent(new CustomEvent('aphelion:tool-visibility', {detail: {tool, visible}}));
  }

  function ensureStylesheet(href) {
    if (document.querySelector('link[rel="stylesheet"][href="' + href + '"]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.addEventListener('load', () => resolve());
      script.addEventListener('error', () => reject(new Error('Failed to load ' + src + '.')));
      document.body.appendChild(script);
    });
  }

  // Scripts load one at a time, each waiting for the previous to finish, rather than all at once -- load
  // order matters here (each vendor file merges its exports into a shared global the next one reads back
  // out of), which a parallel Promise.all wouldn't guarantee.
  async function loadScriptsInOrder(sources) {
    for (const src of sources) {
      await loadScript(src);
    }
  }

  function registerView(tool, mainEl) {
    mainEl.id = 'tool-view-' + tool;
    mainEl.dataset.tool = tool;
    views[tool] = mainEl;
    initializeSearch(mainEl);
  }

  function showView(tool) {
    for (const [otherTool, element] of Object.entries(views)) {
      if (otherTool === tool || element.hidden) continue;
      element.hidden = true;
      dispatchVisibility(otherTool, false);
    }
    views[tool].hidden = false;
    activeTool = tool;
    document.title = TOOL_TITLES[tool] || document.title;
    dispatchVisibility(tool, true);
  }

  function loadView(tool, href) {
    if (loading[tool]) return loading[tool];
    setLoading(true);
    loading[tool] = fetch(href)
      .then((response) => {
        if (!response.ok) throw new Error('Could not load that page (' + response.status + ').');
        return response.text();
      })
      .then((html) => {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const mainEl = doc.querySelector('main.shell');
        if (!mainEl) throw new Error('Could not load that page.');
        (TOOL_STYLES[tool] || []).forEach(ensureStylesheet);
        mainEl.hidden = true;
        registerView(tool, mainEl);
        document.body.appendChild(mainEl);
        const scripts = TOOL_SCRIPTS[tool];
        if (!scripts) return undefined;
        return loadScriptsInOrder(Array.isArray(scripts) ? scripts : [scripts]);
      })
      .finally(() => {
        setLoading(false);
        delete loading[tool];
      });
    return loading[tool];
  }

  function activateTool(tool, href, {pushState = true} = {}) {
    if (!tool) return Promise.resolve();
    if (tool === activeTool) return Promise.resolve();
    const proceed = () => {
      showView(tool);
      if (pushState) window.history.pushState(null, '', href);
    };
    if (views[tool]) {
      proceed();
      return Promise.resolve();
    }
    return loadView(tool, href).then(proceed).catch((error) => {
      console.error(error);
      window.location.href = href;
    });
  }

  // ---- Global search: page navigation + catalog entry lookup, from the sidebar search box ----

  const SEARCH_PAGES = [
    {tool: 'home', href: '/', title: 'Home'},
    {tool: 'file-management', href: '/file-management', title: 'File Management'},
    {tool: 'lore-editor', href: '/lore-editor', title: 'Lore Editor'},
    {tool: 'graph', href: '/graph', title: 'Content Graph'},
  ];

  function hideSearchResults(container) {
    container.hidden = true;
    container.replaceChildren();
  }

  function renderSearchResults(container, query, pages, entries) {
    container.replaceChildren();
    if (!pages.length && !entries.length) {
      const empty = document.createElement('p');
      empty.className = 'search-empty';
      empty.textContent = 'No matches.';
      container.append(empty);
      container.hidden = false;
      return;
    }
    if (pages.length) {
      const heading = document.createElement('p');
      heading.className = 'search-section-heading';
      heading.textContent = 'Pages';
      container.append(heading);
      for (const page of pages) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'search-result';
        button.textContent = page.title;
        button.addEventListener('click', () => {
          activateTool(page.tool, page.href);
          hideSearchResults(container);
        });
        container.append(button);
      }
    }
    if (entries.length) {
      const heading = document.createElement('p');
      heading.className = 'search-section-heading';
      heading.textContent = 'Catalog entries';
      container.append(heading);
      for (const entry of entries) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'search-result';
        const name = document.createElement('strong');
        name.textContent = entry.name || entry.base_name || entry.type_path || 'Unnamed entry';
        const meta = document.createElement('span');
        meta.className = 'search-result-meta';
        meta.textContent = entry.type_path || '';
        button.append(name, meta);
        button.addEventListener('click', () => {
          activateTool('lore-editor', '/lore-editor').then(() => {
            window.dispatchEvent(new CustomEvent('aphelion:search-select-entry', {detail: {typePath: entry.type_path, query}}));
          });
          hideSearchResults(container);
        });
        container.append(button);
      }
    }
    container.hidden = false;
  }

  async function runSearch(query, resultsContainer) {
    const trimmed = query.trim();
    if (!trimmed) {
      hideSearchResults(resultsContainer);
      return;
    }
    const lowerQuery = trimmed.toLowerCase();
    const matchedPages = SEARCH_PAGES.filter((page) => page.title.toLowerCase().includes(lowerQuery));
    let entries = [];
    try {
      const response = await fetch('/api/review?q=' + encodeURIComponent(trimmed) + '&limit=6');
      if (response.ok) {
        const payload = await response.json();
        entries = payload.entries || [];
      }
    } catch (error) {
      // Best-effort: page matches still render even if the catalog search fails.
    }
    renderSearchResults(resultsContainer, trimmed, matchedPages, entries);
  }

  function initializeSearch(mainEl) {
    const input = mainEl.querySelector('.global-search-input');
    const results = mainEl.querySelector('.global-search-results');
    if (!input || !results) return;
    let debounceTimer = null;
    input.addEventListener('input', () => {
      window.clearTimeout(debounceTimer);
      const query = input.value;
      debounceTimer = window.setTimeout(() => runSearch(query, results), 200);
    });
    input.addEventListener('focus', () => {
      if (input.value.trim()) runSearch(input.value, results);
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') hideSearchResults(results);
    });
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('.sidebar-search')) return;
    document.querySelectorAll('.global-search-results').forEach((element) => {
      element.hidden = true;
      element.replaceChildren();
    });
  });

  function onNavClick(event) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a.tool-pill[href]');
    if (!link) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const tool = toolFromPath(url.pathname);
    if (!tool) return;
    event.preventDefault();
    activateTool(tool, url.pathname);
  }

  function onPopState() {
    const tool = toolFromPath(window.location.pathname);
    if (!tool) return;
    activateTool(tool, window.location.pathname, {pushState: false});
  }

  function init() {
    const currentTool = toolFromPath(window.location.pathname);
    const mainEl = document.querySelector('main.shell');
    if (currentTool && mainEl) {
      registerView(currentTool, mainEl);
      activeTool = currentTool;
      document.title = TOOL_TITLES[currentTool] || document.title;
    }
    document.addEventListener('click', onNavClick);
    window.addEventListener('popstate', onPopState);
  }

  if (typeof document !== 'undefined') {
    init();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {toolFromPath};
  }
})();
