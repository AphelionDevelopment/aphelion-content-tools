(() => {
  'use strict';

  const TOOL_ROUTES = {'/': 'home', '/lore-editor': 'lore-editor', '/graph': 'graph'};
  const TOOL_SCRIPTS = {home: '/app.js', 'lore-editor': '/lore-editor.js', graph: '/graph.js'};
  const TOOL_STYLES = {home: ['/styles.css'], 'lore-editor': ['/styles.css'], graph: ['/graph.css']};
  const TOOL_TITLES = {
    home: 'Aphelion Content Tools',
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

  function registerView(tool, mainEl) {
    mainEl.id = 'tool-view-' + tool;
    mainEl.dataset.tool = tool;
    views[tool] = mainEl;
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
        return new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = TOOL_SCRIPTS[tool];
          script.addEventListener('load', () => resolve());
          script.addEventListener('error', () => reject(new Error('Failed to load ' + tool + '.')));
          document.body.appendChild(script);
        });
      })
      .finally(() => {
        setLoading(false);
        delete loading[tool];
      });
    return loading[tool];
  }

  function activateTool(tool, href, {pushState = true} = {}) {
    if (!tool || tool === activeTool) return;
    const proceed = () => {
      showView(tool);
      if (pushState) window.history.pushState(null, '', href);
    };
    if (views[tool]) {
      proceed();
      return;
    }
    loadView(tool, href).then(proceed).catch((error) => {
      console.error(error);
      window.location.href = href;
    });
  }

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
