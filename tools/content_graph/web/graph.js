(() => {
  'use strict';

  const KIND_COLORS = {
    module: {nova: '#55d6ff', aphelion: '#52f0b0'},
    master_file: '#f2a9dd',
    core_file: '#d16aff',
    directory: '#8f6fae',
    file: '#6c5a82',
  };
  const EDGE_COLORS = {
    master_files_mirror: 'rgba(198, 169, 212, .5)',
    marker_edit: {
      addition: 'rgba(82, 240, 176, .65)',
      removal: 'rgba(240, 120, 120, .65)',
      change: 'rgba(242, 169, 221, .75)',
      unspecified: 'rgba(198, 169, 212, .55)',
    },
    contains: 'rgba(140, 120, 170, .28)',
  };

  const SIM_ITERATIONS = 240;
  const ITERATIONS_PER_FRAME = 4;
  const LIVE_TEMPERATURE = 0.06;
  const LIVE_PHYSICS_NODE_THRESHOLD = 1500;
  const GRID_CELL_SIZE = 90;
  const MAX_SPEED = 60;
  const MAX_RADIUS = 1400;
  const NUDGE_STEPS = 60;
  const MAX_UNRESOLVED_RENDERED = 200;
  const ROOT_DIR_ID = 'dir:.';

  const state = {
    rawGraph: null,
    rawNodeById: new Map(),
    childrenByParent: new Map(),
    parentByChild: new Map(),
    scope: new Set(),
    nodes: [],
    edges: [],
    nodeById: new Map(),
    forces: {
      repulsion: 2600,
      springLength: 70,
      springStrength: 0.02,
      center: 0.004,
    },
    filters: {
      kinds: new Set(['module', 'master_file', 'core_file', 'directory', 'file']),
      owners: new Set(['nova', 'aphelion']),
      relations: new Set(['master_files_mirror', 'marker_edit', 'contains']),
      search: '',
    },
    explorer: {
      expanded: new Set([ROOT_DIR_ID]),
      filterText: '',
    },
    camera: {x: 0, y: 0, scale: 1},
    selectedNodeId: null,
    dragging: false,
    draggingNode: null,
    hasDragged: false,
    lastPointer: null,
    simulationDone: false,
    livePhysics: false,
    simFrameHandle: null,
    perf: {frameMs: 0},
  };

  const canvas = typeof document !== 'undefined' ? document.getElementById('graph-canvas') : null;
  const ctx = canvas ? canvas.getContext('2d') : null;

  async function requestJson(path, options = {}) {
    const response = await fetch(path, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : {};
    if (!response.ok) throw new Error(payload.error || ('Request failed (' + response.status + ')'));
    return payload;
  }

  function setStatus(text) {
    document.getElementById('graph-status').textContent = text;
  }

  function resizeCanvas() {
    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(320, rect.width) * dpr;
    canvas.height = Math.max(320, rect.height) * dpr;
    canvas.style.width = Math.max(320, rect.width) + 'px';
    canvas.style.height = Math.max(320, rect.height) + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function nodeColor(node) {
    if (node.kind === 'module') return KIND_COLORS.module[node.owner] || KIND_COLORS.module.nova;
    if (node.kind === 'master_file') return KIND_COLORS.master_file;
    if (node.kind === 'directory') return KIND_COLORS.directory;
    if (node.kind === 'file') return KIND_COLORS.file;
    return KIND_COLORS.core_file;
  }

  function edgeColor(edge) {
    if (edge.relation === 'marker_edit') {
      return EDGE_COLORS.marker_edit[edge.editType] || EDGE_COLORS.marker_edit.unspecified;
    }
    if (edge.relation === 'contains') return EDGE_COLORS.contains;
    return EDGE_COLORS.master_files_mirror;
  }

  function buildSimulation(graph) {
    const nodeById = new Map();
    const nodes = graph.nodes.map((raw, index) => {
      const angle = (index / graph.nodes.length) * Math.PI * 2;
      const radiusSeed = 200 + (index % 40) * 12;
      const node = {
        id: raw.id,
        kind: raw.kind,
        owner: raw.owner || null,
        moduleId: raw.module_id || null,
        path: raw.path || null,
        name: raw.name || null,
        corePath: raw.core_path || null,
        hasReadme: raw.has_readme,
        markerCount: raw.marker_count || 0,
        degree: 0,
        x: Math.cos(angle) * radiusSeed,
        y: Math.sin(angle) * radiusSeed,
        vx: 0,
        vy: 0,
        pinned: false,
        visible: true,
      };
      nodeById.set(node.id, node);
      return node;
    });
    const edges = [];
    for (const rawEdge of graph.edges) {
      const source = nodeById.get(rawEdge.source);
      const target = nodeById.get(rawEdge.target);
      if (!source || !target) continue;
      source.degree += 1;
      target.degree += 1;
      edges.push({
        source,
        target,
        relation: rawEdge.relation,
        editType: rawEdge.edit_type || null,
        attribution: rawEdge.attribution || null,
        lineNumber: rawEdge.line_number || null,
        rawLabel: rawEdge.raw_label || null,
        originalText: rawEdge.original_text || null,
      });
    }
    for (const node of nodes) {
      node.radius = 3 + Math.min(14, Math.sqrt(node.degree + 1) * 2.2);
    }
    return {nodes, edges, nodeById};
  }

  function buildGrid(nodes) {
    const grid = new Map();
    for (const node of nodes) {
      const gx = Math.floor(node.x / GRID_CELL_SIZE);
      const gy = Math.floor(node.y / GRID_CELL_SIZE);
      const key = gx + ',' + gy;
      let bucket = grid.get(key);
      if (!bucket) {
        bucket = [];
        grid.set(key, bucket);
      }
      bucket.push(node);
    }
    return grid;
  }

  function simulationStep(nodes, edges, temperature) {
    const grid = buildGrid(nodes);
    const forces = state.forces;
    for (const node of nodes) {
      if (node.pinned) { node.vx = 0; node.vy = 0; continue; }
      let fx = 0;
      let fy = 0;
      const gx = Math.floor(node.x / GRID_CELL_SIZE);
      const gy = Math.floor(node.y / GRID_CELL_SIZE);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const bucket = grid.get((gx + dx) + ',' + (gy + dy));
          if (!bucket) continue;
          for (const other of bucket) {
            if (other === node) continue;
            let ddx = node.x - other.x;
            let ddy = node.y - other.y;
            let distSq = ddx * ddx + ddy * ddy;
            if (distSq < 0.01) { ddx = (Math.random() - 0.5); ddy = (Math.random() - 0.5); distSq = 1; }
            if (distSq > (GRID_CELL_SIZE * 1.5) ** 2) continue;
            const dist = Math.sqrt(distSq);
            const force = forces.repulsion / distSq;
            fx += (ddx / dist) * force;
            fy += (ddy / dist) * force;
          }
        }
      }
      fx += -node.x * forces.center;
      fy += -node.y * forces.center;
      node.vx = (node.vx + fx) * 0.85;
      node.vy = (node.vy + fy) * 0.85;
      const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
      if (speed > MAX_SPEED) {
        node.vx = (node.vx / speed) * MAX_SPEED;
        node.vy = (node.vy / speed) * MAX_SPEED;
      }
    }
    for (const edge of edges) {
      if (edge.source.pinned && edge.target.pinned) continue;
      const dx = edge.target.x - edge.source.x;
      const dy = edge.target.y - edge.source.y;
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const displacement = dist - forces.springLength;
      const force = displacement * forces.springStrength;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      edge.source.vx += fx;
      edge.source.vy += fy;
      edge.target.vx -= fx;
      edge.target.vy -= fy;
    }
    for (const node of nodes) {
      if (node.pinned) continue;
      node.x += node.vx * temperature;
      node.y += node.vy * temperature;
      const radius = Math.sqrt(node.x * node.x + node.y * node.y);
      if (radius > MAX_RADIUS) {
        const scale = MAX_RADIUS / radius;
        node.x *= scale;
        node.y *= scale;
      }
    }
  }

  function runSimulation(nodes, edges, onDone) {
    if (state.simFrameHandle !== null) {
      window.cancelAnimationFrame(state.simFrameHandle);
      state.simFrameHandle = null;
    }
    const live = nodes.length > 0 && nodes.length <= LIVE_PHYSICS_NODE_THRESHOLD;
    state.livePhysics = live;
    let iteration = 0;
    let settled = false;
    let lastTimestamp = null;
    function frame(timestamp) {
      if (lastTimestamp !== null) state.perf.frameMs = timestamp - lastTimestamp;
      lastTimestamp = timestamp;
      if (iteration < SIM_ITERATIONS) {
        for (let i = 0; i < ITERATIONS_PER_FRAME && iteration < SIM_ITERATIONS; i++, iteration++) {
          const temperature = 1 - (iteration / SIM_ITERATIONS);
          simulationStep(nodes, edges, Math.max(0.05, temperature));
        }
        draw();
        if (iteration >= SIM_ITERATIONS && !live) {
          state.simulationDone = true;
          state.simFrameHandle = null;
          state.perf.frameMs = 0;
          onDone();
          return;
        }
        state.simFrameHandle = window.requestAnimationFrame(frame);
        return;
      }
      if (!settled) {
        settled = true;
        state.simulationDone = true;
        onDone();
      }
      simulationStep(nodes, edges, LIVE_TEMPERATURE);
      draw();
      state.simFrameHandle = window.requestAnimationFrame(frame);
    }
    state.simFrameHandle = window.requestAnimationFrame(frame);
  }

  function nudgeSimulation() {
    if (state.livePhysics) return;
    if (state.simFrameHandle !== null) {
      window.cancelAnimationFrame(state.simFrameHandle);
      state.simFrameHandle = null;
    }
    const nodes = state.nodes;
    const edges = state.edges;
    let steps = 0;
    let lastTimestamp = null;
    function frame(timestamp) {
      if (lastTimestamp !== null) state.perf.frameMs = timestamp - lastTimestamp;
      lastTimestamp = timestamp;
      for (let i = 0; i < ITERATIONS_PER_FRAME && steps < NUDGE_STEPS; i++, steps++) {
        simulationStep(nodes, edges, 0.2);
      }
      draw();
      if (steps < NUDGE_STEPS) {
        state.simFrameHandle = window.requestAnimationFrame(frame);
      } else {
        state.simFrameHandle = null;
        state.perf.frameMs = 0;
        renderPhysicsStats();
      }
    }
    state.simFrameHandle = window.requestAnimationFrame(frame);
  }

  function nodeMatchesFilters(node) {
    if (!state.filters.kinds.has(node.kind)) return false;
    if ((node.kind === 'module' || node.kind === 'master_file') && node.owner && !state.filters.owners.has(node.owner)) return false;
    if (state.filters.search) {
      const haystack = (node.moduleId || node.path || node.corePath || node.id || '').toLowerCase();
      if (!haystack.includes(state.filters.search)) return false;
    }
    return true;
  }

  function applyFilters() {
    for (const node of state.nodes) {
      node.visible = nodeMatchesFilters(node);
    }
    const visibleCount = state.nodes.filter((node) => node.visible).length;
    const summary = document.getElementById('scope-summary');
    if (summary) summary.textContent = visibleCount + ' of ' + state.nodes.length + ' nodes shown';
    renderPhysicsStats();
    draw();
  }

  function worldToScreen(x, y) {
    return {
      x: (x * state.camera.scale) + (canvas.clientWidth / 2) + state.camera.x,
      y: (y * state.camera.scale) + (canvas.clientHeight / 2) + state.camera.y,
    };
  }

  function screenToWorld(x, y) {
    return {
      x: (x - (canvas.clientWidth / 2) - state.camera.x) / state.camera.scale,
      y: (y - (canvas.clientHeight / 2) - state.camera.y) / state.camera.scale,
    };
  }

  function draw() {
    if (!canvas.clientWidth) return;
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.save();
    for (const edge of state.edges) {
      if (!edge.source.visible || !edge.target.visible) continue;
      if (!state.filters.relations.has(edge.relation)) continue;
      const a = worldToScreen(edge.source.x, edge.source.y);
      const b = worldToScreen(edge.target.x, edge.target.y);
      ctx.strokeStyle = edgeColor(edge);
      ctx.lineWidth = edge.relation === 'marker_edit' ? 1.4 : (edge.relation === 'contains' ? 0.6 : 1);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    for (const node of state.nodes) {
      if (!node.visible) continue;
      const p = worldToScreen(node.x, node.y);
      const r = node.radius * state.camera.scale;
      if (p.x < -r || p.y < -r || p.x > canvas.clientWidth + r || p.y > canvas.clientHeight + r) continue;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(1.5, r), 0, Math.PI * 2);
      ctx.fillStyle = nodeColor(node);
      ctx.fill();
      if (node.pinned) {
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = 'rgba(255, 247, 255, .6)';
        ctx.stroke();
      }
      if (node.id === state.selectedNodeId) {
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#fff7ff';
        ctx.stroke();
      }
      if (state.camera.scale > 2.2 || (state.camera.scale > 0.9 && node.degree > 3)) {
        ctx.fillStyle = 'rgba(248, 234, 255, .85)';
        ctx.font = '11px system-ui, sans-serif';
        const label = node.moduleId || node.corePath || node.name || node.path || node.id;
        ctx.fillText(label, p.x + r + 3, p.y + 3);
      }
    }
    ctx.restore();
  }

  function findNodeAt(screenX, screenY) {
    const world = screenToWorld(screenX, screenY);
    let closest = null;
    let closestDist = Infinity;
    for (const node of state.nodes) {
      if (!node.visible) continue;
      const dx = node.x - world.x;
      const dy = node.y - world.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const hitRadius = Math.max(6, node.radius + 3 / state.camera.scale);
      if (dist <= hitRadius && dist < closestDist) {
        closest = node;
        closestDist = dist;
      }
    }
    return closest;
  }

  function renderNodeDetail(node) {
    const container = document.getElementById('node-detail');
    if (!node) {
      container.innerHTML = '<p class="metadata">Click a node to inspect it.</p>';
      return;
    }
    const rows = [];
    rows.push(['Kind', node.kind]);
    if (node.owner) rows.push(['Owner', node.owner]);
    if (node.moduleId) rows.push(['Module id', node.moduleId]);
    if (node.path) rows.push(['Path', node.path]);
    if (node.corePath) rows.push(['Core path', node.corePath]);
    if (node.kind === 'module') rows.push(['Has readme.md', node.hasReadme ? 'yes' : 'no']);
    if (node.kind === 'core_file') rows.push(['Marker count', String(node.markerCount)]);
    rows.push(['Connections', String(node.degree)]);
    const rowsHtml = rows.map(([label, value]) =>
      '<div class="node-detail-row"><span class="node-detail-label">' + label + ':</span> ' + escapeHtml(String(value)) + '</div>'
    ).join('');
    const connectedEdges = state.edges.filter((edge) => edge.source === node || edge.target === node);
    const edgesHtml = connectedEdges.slice(0, 25).map((edge) => {
      const other = edge.source === node ? edge.target : edge.source;
      const otherLabel = other.moduleId || other.corePath || other.name || other.path || other.id;
      const detail = edge.relation === 'marker_edit'
        ? (edge.editType || 'edit') + (edge.lineNumber ? (' @ line ' + edge.lineNumber) : '')
        : (edge.relation === 'contains' ? 'contains' : 'master_files mirror');
      return '<div class="node-detail-row">' + escapeHtml(otherLabel) + ' — <span class="node-detail-label">' + escapeHtml(detail) + '</span></div>';
    }).join('');
    container.innerHTML = rowsHtml + '<h3>Edges (' + connectedEdges.length + ')</h3>' + (edgesHtml || '<p class="metadata">None</p>');
  }

  function tooltipText(node) {
    const parts = [node.moduleId || node.corePath || node.name || node.path || node.id];
    if (node.owner) parts.push(node.owner);
    parts.push(node.kind);
    if (node.kind === 'module') parts.push(node.hasReadme ? 'has readme.md' : 'no readme.md');
    if (node.kind === 'core_file') parts.push(node.markerCount + ' marker(s)');
    parts.push(node.degree + ' connection(s)');
    return parts.join(' · ');
  }

  function showTooltip(node, clientX, clientY, rect) {
    const tooltip = document.getElementById('node-tooltip');
    if (!tooltip) return;
    tooltip.textContent = tooltipText(node);
    tooltip.style.left = (clientX - rect.left + 14) + 'px';
    tooltip.style.top = (clientY - rect.top + 14) + 'px';
    tooltip.hidden = false;
  }

  function hideTooltip() {
    const tooltip = document.getElementById('node-tooltip');
    if (tooltip) tooltip.hidden = true;
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }

  function renderPhysicsStats() {
    const container = document.getElementById('physics-stats');
    if (!container) return;
    const visibleCount = state.nodes.filter((node) => node.visible).length;
    const mode = state.livePhysics ? 'Live (continuous)' : 'Static (settled)';
    const frameMs = state.perf.frameMs;
    const frameText = frameMs > 0 ? frameMs.toFixed(1) + ' ms (' + Math.round(1000 / frameMs) + ' fps)' : '—';
    const rows = [
      ['Nodes in scope', state.nodes.length],
      ['Nodes visible', visibleCount],
      ['Edges in scope', state.edges.length],
      ['Simulation mode', mode],
      ['Live physics threshold', LIVE_PHYSICS_NODE_THRESHOLD + ' nodes'],
      ['Frame time', frameText],
    ];
    container.innerHTML = rows.map(([label, value]) =>
      '<div class="node-detail-row"><span class="node-detail-label">' + label + ':</span> ' + escapeHtml(String(value)) + '</div>'
    ).join('');
  }

  function renderUnresolvedMarkers(graph) {
    const list = document.getElementById('unresolved-list');
    const markers = (graph.unresolved_markers || []).slice(0, MAX_UNRESOLVED_RENDERED);
    if (!markers.length) {
      list.innerHTML = '<p class="metadata">None found.</p>';
      return;
    }
    list.innerHTML = markers.map((marker) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(marker.core_file) + ':' + marker.line_number + '</div>' +
      '<div>' + escapeHtml(marker.owner) + ' ' + escapeHtml(marker.edit_type) + ' (' + escapeHtml(marker.attribution) + ')</div>' +
      '<div class="metadata">' + escapeHtml(marker.raw_label || '(no label)') + '</div>' +
      '</div>'
    )).join('');
    const total = (graph.unresolved_markers || []).length;
    if (total > MAX_UNRESOLVED_RENDERED) {
      list.innerHTML += '<p class="metadata">' + (total - MAX_UNRESOLVED_RENDERED) + ' more not shown.</p>';
    }
  }

  // ---- Scope: which nodes are currently eligible for simulation ----

  function defaultScopeNodeIds(rawGraph) {
    const ids = new Set();
    for (const node of rawGraph.nodes) {
      if (node.kind === 'module' || node.kind === 'master_file' || node.kind === 'core_file') ids.add(node.id);
    }
    return ids;
  }

  function applyScope(nextScope) {
    state.scope = nextScope;
    const scopedNodes = state.rawGraph.nodes.filter((node) => nextScope.has(node.id));
    const scopedEdges = state.rawGraph.edges.filter((edge) => nextScope.has(edge.source) && nextScope.has(edge.target));
    const built = buildSimulation({nodes: scopedNodes, edges: scopedEdges});
    state.nodes = built.nodes;
    state.edges = built.edges;
    state.nodeById = built.nodeById;
    state.selectedNodeId = null;
    renderNodeDetail(null);
    applyFilters();
    state.simulationDone = false;
    runSimulation(state.nodes, state.edges, () => applyFilters());
  }

  // ---- Explorer: VS Code-style tree over the full scanned repository ----

  function explorerChildren(nodeId) {
    const ids = state.childrenByParent.get(nodeId) || [];
    return ids.slice().sort((a, b) => {
      const aIsDir = (state.childrenByParent.get(a) || []).length > 0;
      const bIsDir = (state.childrenByParent.get(b) || []).length > 0;
      if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
      const na = state.rawNodeById.get(a);
      const nb = state.rawNodeById.get(b);
      return String((na && (na.name || na.path)) || a).localeCompare(String((nb && (nb.name || nb.path)) || b));
    });
  }

  function computeExplorerKeepSet(filterText) {
    if (!filterText) return null;
    const keep = new Set();
    for (const node of state.rawGraph.nodes) {
      const haystack = (node.path || '').toLowerCase();
      if (!haystack.includes(filterText)) continue;
      let id = node.id;
      while (id && !keep.has(id)) {
        keep.add(id);
        id = state.parentByChild.get(id);
      }
    }
    return keep;
  }

  function collectSubtreeIds(nodeId, out) {
    out.add(nodeId);
    for (const childId of (state.childrenByParent.get(nodeId) || [])) {
      collectSubtreeIds(childId, out);
    }
  }

  function setSubtreeScope(nodeId, included) {
    const subtree = new Set();
    collectSubtreeIds(nodeId, subtree);
    const nextScope = new Set(state.scope);
    for (const id of subtree) {
      if (included) nextScope.add(id);
      else nextScope.delete(id);
    }
    applyScope(nextScope);
    renderExplorer();
  }

  function createExplorerRow(nodeId, depth, keepSet) {
    const node = state.rawNodeById.get(nodeId);
    const wrapper = document.createElement('div');
    if (!node) return wrapper;

    let children = explorerChildren(nodeId);
    if (keepSet) children = children.filter((id) => keepSet.has(id));
    const isExpandable = children.length > 0;
    const isExpanded = keepSet !== null || state.explorer.expanded.has(nodeId);

    const row = document.createElement('div');
    row.className = 'explorer-row';
    row.style.paddingLeft = (depth * 0.9) + 'em';
    row.dataset.id = nodeId;

    const toggle = document.createElement('span');
    toggle.className = 'explorer-toggle' + (isExpandable ? '' : ' empty');
    toggle.textContent = isExpandable ? (isExpanded ? '▾' : '▸') : '';
    row.appendChild(toggle);

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.scope.has(nodeId);
    checkbox.title = 'Show this ' + (isExpandable ? 'folder' : 'file') + ' on the canvas';
    row.appendChild(checkbox);

    const label = document.createElement('span');
    label.className = 'explorer-label';
    label.textContent = node.name || node.path || nodeId;
    label.title = node.path || nodeId;
    row.appendChild(label);
    wrapper.appendChild(row);

    const childrenContainer = document.createElement('div');
    childrenContainer.className = 'explorer-children';
    childrenContainer.hidden = !isExpanded;
    wrapper.appendChild(childrenContainer);

    function renderChildrenIfNeeded() {
      if (childrenContainer.childElementCount || !children.length) return;
      for (const childId of children) {
        childrenContainer.appendChild(createExplorerRow(childId, depth + 1, keepSet));
      }
    }
    if (isExpanded) renderChildrenIfNeeded();

    const toggleExpand = () => {
      if (!isExpandable || keepSet !== null) return;
      const expand = !state.explorer.expanded.has(nodeId);
      if (expand) {
        state.explorer.expanded.add(nodeId);
        renderChildrenIfNeeded();
      } else {
        state.explorer.expanded.delete(nodeId);
      }
      childrenContainer.hidden = !expand;
      toggle.textContent = expand ? '▾' : '▸';
    };
    toggle.addEventListener('click', toggleExpand);
    label.addEventListener('click', toggleExpand);
    checkbox.addEventListener('click', (event) => event.stopPropagation());
    checkbox.addEventListener('change', () => setSubtreeScope(nodeId, checkbox.checked));

    return wrapper;
  }

  function renderExplorer() {
    const container = document.getElementById('explorer-tree');
    if (!container || !state.rawGraph) return;
    const keepSet = computeExplorerKeepSet(state.explorer.filterText);
    container.innerHTML = '';
    container.appendChild(createExplorerRow(ROOT_DIR_ID, 0, keepSet));
  }

  function attachExplorerEvents() {
    const filterInput = document.getElementById('explorer-filter');
    if (filterInput) {
      let filterTimer = null;
      filterInput.addEventListener('input', (event) => {
        window.clearTimeout(filterTimer);
        filterTimer = window.setTimeout(() => {
          state.explorer.filterText = event.target.value.trim().toLowerCase();
          renderExplorer();
        }, 150);
      });
    }
    const resetButton = document.getElementById('explorer-reset');
    if (resetButton) {
      resetButton.addEventListener('click', () => {
        applyScope(defaultScopeNodeIds(state.rawGraph));
        renderExplorer();
      });
    }
  }

  // ---- Interactions ----

  function attachInteractions() {
    canvas.addEventListener('mousedown', (event) => {
      const rect = canvas.getBoundingClientRect();
      const hit = findNodeAt(event.clientX - rect.left, event.clientY - rect.top);
      state.draggingNode = hit || null;
      state.dragging = !hit;
      state.hasDragged = false;
      state.lastPointer = {x: event.clientX, y: event.clientY};
    });
    window.addEventListener('mouseup', () => {
      if (state.draggingNode && state.hasDragged) nudgeSimulation();
      state.dragging = false;
      state.draggingNode = null;
      state.lastPointer = null;
    });
    window.addEventListener('mousemove', (event) => {
      if (!state.lastPointer) return;
      if (state.draggingNode) {
        state.hasDragged = true;
        state.draggingNode.pinned = true;
        state.draggingNode.x += (event.clientX - state.lastPointer.x) / state.camera.scale;
        state.draggingNode.y += (event.clientY - state.lastPointer.y) / state.camera.scale;
        state.draggingNode.vx = 0;
        state.draggingNode.vy = 0;
        state.lastPointer = {x: event.clientX, y: event.clientY};
        draw();
        return;
      }
      if (!state.dragging) return;
      state.hasDragged = true;
      state.camera.x += event.clientX - state.lastPointer.x;
      state.camera.y += event.clientY - state.lastPointer.y;
      state.lastPointer = {x: event.clientX, y: event.clientY};
      draw();
    });
    canvas.addEventListener('mousemove', (event) => {
      if (state.dragging || state.draggingNode) { hideTooltip(); return; }
      const rect = canvas.getBoundingClientRect();
      const node = findNodeAt(event.clientX - rect.left, event.clientY - rect.top);
      if (!node) { hideTooltip(); return; }
      showTooltip(node, event.clientX, event.clientY, rect);
    });
    canvas.addEventListener('mouseleave', hideTooltip);
    canvas.addEventListener('click', (event) => {
      if (state.hasDragged) { state.hasDragged = false; return; }
      const rect = canvas.getBoundingClientRect();
      const node = findNodeAt(event.clientX - rect.left, event.clientY - rect.top);
      state.selectedNodeId = node ? node.id : null;
      renderNodeDetail(node);
      draw();
    });
    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const pointer = {x: event.clientX - rect.left, y: event.clientY - rect.top};
      const before = screenToWorld(pointer.x, pointer.y);
      const zoomFactor = event.deltaY < 0 ? 1.1 : 0.9;
      state.camera.scale = Math.min(6, Math.max(0.1, state.camera.scale * zoomFactor));
      const after = worldToScreen(before.x, before.y);
      state.camera.x += pointer.x - after.x;
      state.camera.y += pointer.y - after.y;
      draw();
    }, {passive: false});
    window.addEventListener('resize', () => { resizeCanvas(); draw(); });

    document.querySelectorAll('[data-kind]').forEach((input) => {
      input.addEventListener('change', () => {
        if (input.checked) state.filters.kinds.add(input.dataset.kind);
        else state.filters.kinds.delete(input.dataset.kind);
        applyFilters();
      });
    });
    document.querySelectorAll('[data-owner]').forEach((input) => {
      input.addEventListener('change', () => {
        if (input.checked) state.filters.owners.add(input.dataset.owner);
        else state.filters.owners.delete(input.dataset.owner);
        applyFilters();
      });
    });
    document.querySelectorAll('[data-relation]').forEach((input) => {
      input.addEventListener('change', () => {
        if (input.checked) state.filters.relations.add(input.dataset.relation);
        else state.filters.relations.delete(input.dataset.relation);
        draw();
      });
    });
    let searchTimer = null;
    document.getElementById('node-search').addEventListener('input', (event) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.filters.search = event.target.value.trim().toLowerCase();
        applyFilters();
      }, 150);
    });

    document.querySelectorAll('[data-force]').forEach((input) => {
      input.addEventListener('input', () => {
        state.forces[input.dataset.force] = Number(input.value);
        if (!state.livePhysics && state.simulationDone) {
          state.simulationDone = false;
          runSimulation(state.nodes, state.edges, () => applyFilters());
        }
      });
    });

    attachExplorerEvents();
  }

  async function pollScan(runId) {
    const payload = await requestJson('/api/tools/runs/' + encodeURIComponent(runId));
    document.getElementById('scan-output').textContent = payload.output || '';
    if (payload.status === 'queued' || payload.status === 'running') {
      window.setTimeout(() => pollScan(runId).catch((error) => {
        document.getElementById('scan-output').textContent = error.message;
      }), 750);
      return;
    }
    document.getElementById('scan-button').disabled = false;
    if (payload.status === 'succeeded') {
      await loadGraph();
    } else {
      setStatus('Scan did not complete successfully — see output below.');
    }
  }

  async function runScan() {
    document.getElementById('scan-button').disabled = true;
    document.getElementById('scan-output').hidden = false;
    document.getElementById('scan-output').textContent = 'Starting scan…';
    try {
      const payload = await requestJson('/api/tools/scan-content', {method: 'POST'});
      await pollScan(payload.run_id);
    } catch (error) {
      document.getElementById('scan-output').textContent = error.message;
      document.getElementById('scan-button').disabled = false;
    }
  }

  async function loadGraph() {
    setStatus('Loading…');
    const payload = await requestJson('/api/graph');
    if (!payload.scanned) {
      setStatus('No content graph has been scanned yet. Click "Scan modular content" to build one.');
      return;
    }
    state.rawGraph = payload.graph;
    state.rawNodeById = new Map(payload.graph.nodes.map((node) => [node.id, node]));
    state.childrenByParent = new Map();
    state.parentByChild = new Map();
    for (const edge of payload.graph.edges) {
      if (edge.relation !== 'contains') continue;
      state.parentByChild.set(edge.target, edge.source);
      let bucket = state.childrenByParent.get(edge.source);
      if (!bucket) { bucket = []; state.childrenByParent.set(edge.source, bucket); }
      bucket.push(edge.target);
    }
    const manifest = payload.manifest;
    const counts = payload.graph.counts;
    setStatus(
      'Scanned ' + manifest.generated_at + ' at revision ' + manifest.game_repo_revision.slice(0, 12) +
      ' — ' + counts.module_count + ' modules, ' + counts.master_files_count + ' master_files overrides, ' +
      counts.marker_count + ' markers (' + counts.unresolved_marker_count + ' unresolved), ' +
      counts.file_count + ' tracked files across ' + counts.directory_count + ' directories.'
    );
    renderUnresolvedMarkers(payload.graph);
    state.explorer.expanded = new Set([ROOT_DIR_ID]);
    renderExplorer();
    applyScope(defaultScopeNodeIds(payload.graph));
  }

  function renderDebugResults(items, emptyMessage, renderItem) {
    const container = document.getElementById('debug-results');
    if (!items.length) {
      container.innerHTML = '<p class="metadata">' + escapeHtml(emptyMessage) + '</p>';
      return;
    }
    container.innerHTML = items.map(renderItem).join('');
  }

  async function runCoreFileLookup() {
    const coreFile = document.getElementById('debug-core-file').value.trim();
    if (!coreFile) {
      renderDebugResults([], 'Enter a core file path first.', () => '');
      return;
    }
    const payload = await requestJson('/api/graph/edits?core_file=' + encodeURIComponent(coreFile));
    if (!payload.scanned) {
      renderDebugResults([], 'No content graph has been scanned yet.', () => '');
      return;
    }
    renderDebugResults(payload.edits, 'No edits found for that core file.', (edit) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(edit.owner) + ' ' + escapeHtml(edit.edit_type) +
      (edit.line_number ? (' @ line ' + edit.line_number) : '') +
      ' (' + (edit.resolved ? 'resolved' : 'unresolved') + ')</div>' +
      '<div class="metadata">' + escapeHtml(edit.raw_label || edit.source_module_id || '(no label)') + '</div>' +
      '</div>'
    ));
  }

  async function runMissingReadmeLookup() {
    const payload = await requestJson('/api/graph/modules?missing_readme=true');
    if (!payload.scanned) {
      renderDebugResults([], 'No content graph has been scanned yet.', () => '');
      return;
    }
    renderDebugResults(payload.modules, 'Every module has a readme.md.', (module) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(module.owner) + ':' + escapeHtml(module.module_id) + '</div>' +
      '<div class="metadata">' + escapeHtml(module.path) + '</div>' +
      '</div>'
    ));
  }

  async function runUnresolvedLookup() {
    const payload = await requestJson('/api/graph/unresolved');
    if (!payload.scanned) {
      renderDebugResults([], 'No content graph has been scanned yet.', () => '');
      return;
    }
    renderDebugResults(payload.unresolved_markers, 'No unresolved markers.', (marker) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(marker.core_file) + ':' + marker.line_number + '</div>' +
      '<div>' + escapeHtml(marker.owner) + ' ' + escapeHtml(marker.edit_type) + ' (' + escapeHtml(marker.attribution) + ')</div>' +
      '<div class="metadata">' + escapeHtml(marker.raw_label || '(no label)') + '</div>' +
      '</div>'
    ));
  }

  function attachStaticEvents() {
    document.getElementById('scan-button').addEventListener('click', () => runScan().catch((error) => setStatus(error.message)));
    document.getElementById('refresh-button').addEventListener('click', () => loadGraph().catch((error) => setStatus(error.message)));
    document.getElementById('debug-core-file-button').addEventListener('click', () => runCoreFileLookup().catch((error) => setStatus(error.message)));
    document.getElementById('debug-core-file').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runCoreFileLookup().catch((error) => setStatus(error.message));
    });
    document.getElementById('debug-missing-readme-button').addEventListener('click', () => runMissingReadmeLookup().catch((error) => setStatus(error.message)));
    document.getElementById('debug-unresolved-button').addEventListener('click', () => runUnresolvedLookup().catch((error) => setStatus(error.message)));
    const regenerateButton = document.getElementById('regenerate-layout-button');
    if (regenerateButton) {
      regenerateButton.addEventListener('click', () => applyScope(new Set(state.scope)));
    }
  }

  function init() {
    resizeCanvas();
    attachInteractions();
    attachStaticEvents();
    window.setInterval(renderPhysicsStats, 500);
    loadGraph().catch((error) => setStatus(error.message));
  }

  if (typeof document !== 'undefined') {
    init();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      state,
      MAX_SPEED,
      MAX_RADIUS,
      LIVE_PHYSICS_NODE_THRESHOLD,
      buildSimulation,
      buildGrid,
      simulationStep,
      nodeMatchesFilters,
      tooltipText,
      defaultScopeNodeIds,
      computeExplorerKeepSet,
      collectSubtreeIds,
    };
  }
})();
