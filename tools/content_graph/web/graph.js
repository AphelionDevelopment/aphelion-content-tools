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
    module_reference: 'rgba(255, 196, 92, .6)',
    core_reference: 'rgba(255, 148, 92, .6)',
  };
  const SELECTED_NODE_COLOR = '#fff7ff';

  // Ground-up rebuild: the layout math below (d3-force, deterministic packed-grid placement for huge
  // scopes) is unchanged from the previous version -- it was never the source of the pinwheel/flip-flop/
  // snap-zoom bugs or the "d3 is not defined"/no-motion regression. What changed is *rendering*: this used
  // to be a hand-rolled Canvas2D draw() call plus manual camera/hit-test math, which both couldn't keep a
  // 30,000-node catalog interactive and was where every visual regression lived. Rendering, picking
  // (hover/click), panning/zooming, and node dragging are now owned by Sigma.js (WebGL, vendored as
  // sigma.min.js) operating on a graphology.Graph (vendored as graphology.umd.min.js) -- the combination
  // the sigma.js team itself documents for pairing with an externally-computed layout. Each d3-force tick
  // (or each packed-grid placement) writes positions into the graphology graph; Sigma listens to
  // graphology's own change events and redraws on the GPU, so there is no manual draw()/hit-grid/camera-
  // matrix code left to regress.
  const LIVE_PHYSICS_NODE_THRESHOLD = 1500;
  // Base value for a small graph's cluster ring radius -- scales up with active node count (see
  // computeSpacingScale) so thousands of nodes aren't forced into the same fixed-size canvas area a few
  // hundred nodes would use.
  const BASE_CLUSTER_RADIUS = 650;
  const SPACING_BASELINE_NODES = 400;
  // There's no hard ceiling on how far a graph this size legitimately needs to spread -- this just keeps
  // computeSpacingScale's sqrt growth bounded by default. state.spacing.unlimited (a user-facing toggle)
  // bypasses this entirely rather than raising it further, for whoever needs more than 1000x.
  const MAX_SPACING_SCALE = 1000;
  // Above this many active nodes, the *default* ("auto") seed shape switches from a physics-settled
  // spiral to a deterministic packed grid (fast, degree-sorted, no overlap by construction) -- see
  // resolveSeedShape. This is purely about which seed shape auto picks; it's independent of
  // state.isHugeScope below (the settle-tick cap), which is a node-count performance safeguard that
  // applies no matter which seed shape was actually used.
  const LARGE_GRAPH_NODE_THRESHOLD = 4000;
  // A hard cap on settle ticks for isHugeScope scopes, independent of alpha decay -- at tens of
  // thousands of nodes, natural alpha decay would take far too long (and cost far too much per tick) to
  // reach its own stopping point. A good seed already did most of the organizing, so this only needs
  // enough ticks to resolve local overlap/spacing, not to converge a whole graph from scratch.
  const MAX_SETTLE_TICKS_HUGE = 60;
  const GRID_PACK_CELL_SIZE = 16;
  const MAX_UNRESOLVED_RENDERED = 200; // retained only for the counts line in setStatus(); see modular-debug.js for the list itself
  const ROOT_DIR_ID = 'dir:.';

  // The "everything on" state for each filter axis -- shared between state.filters' own initial value and
  // the explorer's Tick all / Untick all handlers (see attachExplorerEvents), so the two can't drift out
  // of sync with each other by hardcoding the same lists twice.
  const ALL_FILTER_KINDS = ['module', 'master_file', 'core_file', 'directory', 'file'];
  const ALL_FILTER_OWNERS = ['nova', 'aphelion'];
  const ALL_FILTER_RELATIONS = ['master_files_mirror', 'marker_edit', 'contains', 'module_reference', 'core_reference'];

  // Hop-distance tier palette for ego view (see setEgoFilter) -- brightest/most saturated at the ego node
  // itself, progressively dimmer/greyer the further out a node or edge sits, capped at the last tier for
  // anything beyond it.
  const EGO_TIER_COLORS = ['#fff7ff', '#55d6ff', '#9614d0', '#6c5a82', '#4a3f57'];

  const state = {
    rawGraph: null,
    rawNodeById: new Map(),
    childrenByParent: new Map(),
    parentByChild: new Map(),
    scope: new Set(),
    nodes: [],
    edges: [],
    // Recomputed by applyFilters(): the subset of nodes/edges actually visible under the current
    // kind/owner/search filters. The physics simulation only ever operates on these -- a node the
    // filters hide is frozen in place and stops exerting force on anything, instead of continuing to
    // silently shove visible nodes around (and burn CPU) while invisible.
    activeNodes: [],
    activeEdges: [],
    nodeById: new Map(),
    // The graphology.Graph backing the current Sigma renderer -- rebuilt (not mutated node-by-node)
    // every time the scope changes; positions/visibility within a stable scope are bulk-updated on it
    // every d3 tick / filter change instead (see syncPositionsToGraphology / syncVisibilityToGraphology).
    graphology: null,
    renderer: null,
    forces: {
      repulsion: 2600,
      springLength: 70,
      springStrength: 0.02,
      center: 0.004,
      clusterStrength: 0.025,
      // Extra multiplier on center pull applied only to degree-0 nodes -- see createCenterPullForce.
      // Nothing else reels an unconnected node back in (no link force to any neighbor), so without this
      // it's the one case that can drift arbitrarily far under repulsion alone.
      isolatedPull: 4,
    },
    // Simulation-wide tuning that isn't a per-node force -- see createSimulation/syncSimulationTuningToSimulation.
    simulationTuning: {
      velocityDecay: 0.4, // d3 default; higher = more friction (settles faster, less momentum)
      alphaDecay: 0.0228, // d3 default; higher = cools/settles faster
      // The resting alphaTarget a "live" scope (see resolveLivePhysics) sits at once its initial settle
      // finishes -- this IS the "slow drift" a settled scope keeps making forever; a live slider instead
      // of a fixed constant so it can be sped up (or calmed further) directly instead of just endured.
      ambientAlpha: 0.02,
      // One-shot random velocity kick applied to every unfixed active node by jiggleSimulation() -- an
      // escape hatch for a layout stuck in a lopsided local arrangement, distinct from the continuous,
      // gentle ambientAlpha motion above.
      jiggleStrength: 200,
      theta: 0.9, // Barnes-Hut approximation factor; higher = faster but less accurate repulsion
      collideEnabled: true,
      collidePadding: 2,
      collideStrength: 1,
      // Extra collision-radius buffer that scales with a node's own degree, on top of collidePadding --
      // separate from its *drawn* radius, so a well-connected hub can stay visually modest-sized while
      // still being "respected": nothing crowds or buries it. See syncSimulationTuningToSimulation.
      hubCollisionBuffer: 2,
      chargeByDegree: false,
      chargeByDegreeFactor: 0.15,
    },
    groupByKind: true,
    // Independent of groupByKind -- see clusterKey. Both, either, or neither can be active.
    groupByOwner: true,
    // Spacing (cluster ring radius / packed-grid cell size) either auto-scales with the current active
    // node count, or is pinned to a manual multiplier -- see computeSpacingScale. "unlimited" bypasses
    // MAX_SPACING_SCALE entirely (auto mode) and raises the manual slider's own HTML max attribute.
    spacing: {
      autoScale: true,
      manualScale: 1,
      unlimited: false,
    },
    spacingScale: 1,
    clusterAnchors: new Map(),
    // User's chosen initial-placement shape ('auto'|'spiral'|'packed'|'grid'|'random') -- see
    // resolveSeedShape/buildSimulation. 'auto' resolves to 'spiral' or 'packed' based on
    // LARGE_GRAPH_NODE_THRESHOLD, same as the previous fixed behavior; resolvedSeedShape records which
    // concrete shape actually ran, for display when 'auto' is selected.
    seedShape: 'auto',
    resolvedSeedShape: 'spiral',
    // Set by buildSimulation: true once the active scope is large enough that MAX_SETTLE_TICKS_HUGE
    // applies (see runSimulation) -- a node-count performance safeguard, independent of which seed shape
    // was actually used.
    isHugeScope: false,
    // Organize-around-a-node mode -- see createFocusForce/setFocusNode. distances is a Map<nodeId,
    // hopCount> from nodeId (BFS over state.edges), recomputed whenever the focused node changes.
    focus: {
      enabled: false,
      nodeId: null,
      ringSpacing: 120,
      distances: new Map(),
    },
    // Degree (connection count) range filter -- see nodeMatchesFilters/updateDegreeFilterBounds.
    // degreeMax/max are recomputed per scope; null means "no scope loaded yet."
    degreeFilter: {min: 0, max: null, scopeMax: null},
    // Only used while actively dragging a node (see startDragPhysics) -- separate from the main
    // simulation's temperature/forces so a user can crank up neighbor responsiveness to pull a node
    // and its edges out of a dense cluster, without that also destabilizing the settled layout at rest.
    dragTuning: {
      temperature: 0.06,
      repulsionMultiplier: 1,
    },
    filters: {
      kinds: new Set(ALL_FILTER_KINDS),
      owners: new Set(ALL_FILTER_OWNERS),
      relations: new Set(ALL_FILTER_RELATIONS),
      search: '',
    },
    // Ctrl/Cmd+click a node to isolate its connected component -- see setEgoFilter/clearEgoFilter.
    // distances is the same shape computeFocusDistances returns (Map<nodeId, hopCount>), reused here too.
    egoFilter: {enabled: false, nodeId: null, distances: new Map()},
    // Off by default: dragging a node only moves that node. See downNode/mouseup in attachRendererEvents.
    allowPanWhileDragging: false,
    explorer: {
      expanded: new Set([ROOT_DIR_ID]),
      filterText: '',
      widthManual: false,
    },
    selectedNodeId: null,
    draggingNodeId: null,
    hasDragged: false,
    simulationDone: false,
    livePhysics: false,
    physicsMode: 'auto',
    livePhysicsThreshold: LIVE_PHYSICS_NODE_THRESHOLD,
    // The live d3.forceSimulation for the current scope, or null before the first one is created.
    // forceManyBody/forceLink are kept alongside it since those two force objects cache their own
    // strength/distance and need their setters re-invoked to pick up a slider change; the cluster/center
    // forces are custom ones that read state.forces live every tick, so they never need re-syncing.
    simulation: null,
    forceManyBody: null,
    forceLink: null,
    perf: {frameMs: 0},
  };

  // Snapshot of every Physics-panel default, kept separate from the state object's own initial values so
  // "Reset to defaults" (see resetPhysicsToDefaults) has something to reset *to* after a user has changed
  // things, rather than needing to hardcode the same numbers twice.
  const DEFAULT_FORCES = {repulsion: 2600, springLength: 70, springStrength: 0.02, center: 0.004, clusterStrength: 0.025, isolatedPull: 4};
  const DEFAULT_SIMULATION_TUNING = {velocityDecay: 0.4, alphaDecay: 0.0228, ambientAlpha: 0.02, jiggleStrength: 200, theta: 0.9, collideEnabled: true, collidePadding: 2, collideStrength: 1, hubCollisionBuffer: 2, chargeByDegree: false, chargeByDegreeFactor: 0.15};
  const DEFAULT_DRAG_TUNING = {temperature: 0.06, repulsionMultiplier: 1};
  const DEFAULT_SPACING = {autoScale: true, manualScale: 1, unlimited: false};
  const DEFAULT_FOCUS_RING_SPACING = 120;
  const DEFAULT_GROUP_BY_KIND = true;
  const DEFAULT_GROUP_BY_OWNER = true;
  const DEFAULT_PHYSICS_MODE = 'auto';
  const DEFAULT_SEED_SHAPE = 'auto';

  // Resets every Physics-panel control (Mode, Layout, Forces, Collision, Motion, Dragging, Focus) back to
  // its shipped default, updates each static control's own DOM value/checked state to match (these are
  // permanent controls with persisted state, not auto-rendered -- nothing re-syncs them on its own), and
  // regenerates the layout, since spacing/seed-shape/grouping affect initial placement, not just live forces.
  function resetPhysicsToDefaults() {
    Object.assign(state.forces, DEFAULT_FORCES);
    Object.assign(state.simulationTuning, DEFAULT_SIMULATION_TUNING);
    Object.assign(state.dragTuning, DEFAULT_DRAG_TUNING);
    Object.assign(state.spacing, DEFAULT_SPACING);
    state.groupByKind = DEFAULT_GROUP_BY_KIND;
    state.groupByOwner = DEFAULT_GROUP_BY_OWNER;
    state.physicsMode = DEFAULT_PHYSICS_MODE;
    state.livePhysicsThreshold = LIVE_PHYSICS_NODE_THRESHOLD;
    state.seedShape = DEFAULT_SEED_SHAPE;
    state.allowPanWhileDragging = false;
    clearFocus();
    state.focus.ringSpacing = DEFAULT_FOCUS_RING_SPACING;

    if (typeof document === 'undefined') return;
    document.querySelectorAll('[data-force]').forEach((input) => {
      input.value = String(state.forces[input.dataset.force]);
      bindRangeReadout(input);
    });
    document.querySelectorAll('[data-tuning]').forEach((input) => {
      const value = state.simulationTuning[input.dataset.tuning];
      if (input.type === 'checkbox') input.checked = value;
      else { input.value = String(value); bindRangeReadout(input); }
    });
    document.querySelectorAll('[data-drag]').forEach((input) => {
      input.value = String(state.dragTuning[input.dataset.drag]);
      bindRangeReadout(input);
    });
    document.querySelectorAll('[data-focus]').forEach((input) => {
      input.value = String(state.focus[input.dataset.focus]);
      bindRangeReadout(input);
    });
    const groupByKindInput = document.getElementById('group-by-kind');
    if (groupByKindInput) groupByKindInput.checked = state.groupByKind;
    const groupByOwnerInput = document.getElementById('group-by-owner');
    if (groupByOwnerInput) groupByOwnerInput.checked = state.groupByOwner;
    const autoScaleSpacingInput = document.getElementById('auto-scale-spacing');
    if (autoScaleSpacingInput) autoScaleSpacingInput.checked = state.spacing.autoScale;
    const unlimitedSpacingInput = document.getElementById('unlimited-spacing');
    if (unlimitedSpacingInput) unlimitedSpacingInput.checked = state.spacing.unlimited;
    const spacingScaleInput = document.getElementById('spacing-scale');
    if (spacingScaleInput) {
      spacingScaleInput.disabled = state.spacing.autoScale;
      spacingScaleInput.max = '1000';
      spacingScaleInput.value = String(state.spacing.manualScale);
      bindRangeReadout(spacingScaleInput);
    }
    const seedShapeInput = document.getElementById('seed-shape');
    if (seedShapeInput) seedShapeInput.value = state.seedShape;
    document.querySelectorAll('input[name="physics-mode"]').forEach((input) => {
      input.checked = input.value === state.physicsMode;
    });
    const thresholdInput = document.getElementById('physics-threshold');
    if (thresholdInput) thresholdInput.value = String(state.livePhysicsThreshold);
    const focusEnabledInput = document.getElementById('focus-enabled');
    if (focusEnabledInput) focusEnabledInput.checked = false;
    const allowPanInput = document.getElementById('allow-pan-while-dragging');
    if (allowPanInput) allowPanInput.checked = state.allowPanWhileDragging;

    applyScope(new Set(state.scope));
  }

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
    if (edge.relation === 'module_reference') return EDGE_COLORS.module_reference;
    if (edge.relation === 'core_reference') return EDGE_COLORS.core_reference;
    return EDGE_COLORS.master_files_mirror;
  }

  function nodeLabel(node) {
    return node.moduleId || node.corePath || node.name || node.path || node.id;
  }

  function buildSimulation(graph) {
    const spacingScale = computeSpacingScale(graph.nodes.length);
    state.spacingScale = spacingScale;
    state.isHugeScope = graph.nodes.length > LARGE_GRAPH_NODE_THRESHOLD;
    const shape = resolveSeedShape(graph.nodes.length);
    state.resolvedSeedShape = shape;

    const nodeById = new Map();
    const nodes = graph.nodes.map((raw) => {
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
        fileCount: raw.file_count ?? null,
        totalBytes: raw.total_bytes ?? null,
        sizeBytes: raw.size_bytes ?? null,
        lineCount: raw.line_count ?? null,
        degree: 0,
        x: 0,
        y: 0,
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

    // Positioning happens after degree is known (not before) so packing can prioritize by it -- see
    // packNodesIntoGrid.
    const clusterGroups = new Map();
    for (const node of nodes) {
      const key = clusterKey(node);
      let group = clusterGroups.get(key);
      if (!group) { group = []; clusterGroups.set(key, group); }
      group.push(node);
    }

    // Cluster anchors are needed regardless of which seed shape is placing nodes -- the live cluster
    // force (see createClusterForce), if enabled, still pulls nodes toward them even when the initial
    // seed itself ignores clustering (e.g. 'grid'/'random'). Only 'packed'/'random' actually use
    // clusterFootprintRadius-based footprint sizing, so only those widen the ring for an uneven cluster
    // (e.g. a 25,000-node "file" cluster next to a 5-node "module" one) -- spiral/grid placement don't
    // depend on that widening for their own math.
    let maxClusterSize = 0;
    for (const group of clusterGroups.values()) maxClusterSize = Math.max(maxClusterSize, group.length);
    rebuildClusterAnchors(spacingScale, (shape === 'packed' || shape === 'random') ? maxClusterSize : undefined);

    if (shape === 'packed') placePackedGridSeed(clusterGroups);
    else if (shape === 'grid') placeGlobalGridSeed(nodes, spacingScale);
    else if (shape === 'random') placeRandomSeed(clusterGroups, spacingScale);
    else placeSpiralSeed(nodes, spacingScale);

    return {nodes, edges, nodeById};
  }

  // Which concrete seed shape 'auto' resolves to -- unchanged from the previous fixed behavior (spiral
  // below LARGE_GRAPH_NODE_THRESHOLD, packed above). An explicit non-'auto' choice always wins regardless
  // of node count.
  function resolveSeedShape(nodeCount) {
    if (state.seedShape !== 'auto') return state.seedShape;
    return nodeCount > LARGE_GRAPH_NODE_THRESHOLD ? 'packed' : 'spiral';
  }

  // Spawn near this node's eventual cluster anchor (spread on a small spiral within the cluster) rather
  // than on one global ring shared by every kind -- starting close to the final layout means the physics
  // settle has far less distance to cover and far fewer near-coincident starting points to explosively
  // separate, which is what made large graphs slow and chaotic to lay out.
  function placeSpiralSeed(nodes, spacingScale) {
    nodes.forEach((node, index) => {
      const anchor = clusterAnchor(node);
      const spiralAngle = (index / nodes.length) * Math.PI * 2 * 6;
      const spiralRadius = (60 + (index % 40) * 6) * spacingScale;
      node.x = anchor.x + Math.cos(spiralAngle) * spiralRadius;
      node.y = anchor.y + Math.sin(spiralAngle) * spiralRadius;
    });
  }

  // Deterministic packed grid, per cluster -- avoids overlap by construction rather than relying on
  // pairwise repulsion to slowly diffuse nodes apart. See packNodesIntoGrid for the fill order/jitter.
  function placePackedGridSeed(clusterGroups) {
    for (const [key, group] of clusterGroups) {
      packNodesIntoGrid(group, state.clusterAnchors.get(key) || {x: 0, y: 0}, state.spacingScale);
    }
  }

  // Ignores cluster anchors entirely -- every node (regardless of kind/owner) fills one single packed
  // grid centered on the origin, degree-sorted same as the per-cluster version. A neutral, maximally
  // spread starting point when clustering isn't the point of the current view.
  function placeGlobalGridSeed(nodes, spacingScale) {
    packNodesIntoGrid(nodes, {x: 0, y: 0}, spacingScale);
  }

  // Uniform random scatter within each cluster's own footprint (see clusterFootprintRadius) -- same
  // per-cluster sizing the packed grid uses, but jittered across the whole disc instead of gridded, for
  // a starting point with no placement bias at all beyond which cluster a node belongs to.
  function placeRandomSeed(clusterGroups, spacingScale) {
    for (const [key, group] of clusterGroups) {
      const anchor = state.clusterAnchors.get(key) || {x: 0, y: 0};
      const footprint = clusterFootprintRadius(group.length, spacingScale);
      for (const node of group) {
        const angle = Math.random() * Math.PI * 2;
        // sqrt(random()) rather than a bare random radius -- otherwise points bunch up near the center
        // (uniform radius sampling isn't uniform over the disc's *area*).
        const radius = Math.sqrt(Math.random()) * footprint;
        node.x = anchor.x + Math.cos(angle) * radius;
        node.y = anchor.y + Math.sin(angle) * radius;
      }
    }
  }

  // Nodes are pulled toward a shared anchor point spaced evenly around a ring, based on whichever
  // grouping axes are currently on (kind, owner, both, or neither) -- a lightweight, always-on "cluster
  // force" that organizes the graph into visually distinct regions instead of one undifferentiated blob,
  // without giving up the organic feel of force-directed layout within each cluster. Both clusterKey and
  // clusterKeys() must stay in sync (same key shape for the same toggle state), since clusterAnchor looks
  // a node's key up directly in the ring rebuildClusterAnchors builds from clusterKeys().
  const ALL_KINDS = ['module', 'master_file', 'core_file', 'directory', 'file'];
  const OWNED_KINDS = new Set(['module', 'master_file']);

  function clusterKey(node) {
    const kindPart = state.groupByKind ? node.kind : 'any';
    if (state.groupByOwner && OWNED_KINDS.has(node.kind)) return kindPart + ':' + (node.owner || 'nova');
    return kindPart + ':none';
  }

  // Every distinct key clusterKey can currently produce, for however many grouping axes are active --
  // e.g. both axes on yields the original 7 kind[:owner] buckets; owner-only yields 3 (nova/aphelion/none).
  function clusterKeys() {
    const keys = new Set();
    for (const kind of ALL_KINDS) {
      const kindPart = state.groupByKind ? kind : 'any';
      if (state.groupByOwner && OWNED_KINDS.has(kind)) {
        keys.add(kindPart + ':nova');
        keys.add(kindPart + ':aphelion');
      } else {
        keys.add(kindPart + ':none');
      }
    }
    return [...keys];
  }

  // How much wider than the small-graph baseline the cluster ring / canvas radius should be for a given
  // active node count. Auto mode grows this with sqrt(nodeCount) -- enough nodes crammed onto a
  // fixed-size ring is exactly what forced them to overlap; a manual scale lets a user override it directly.
  function computeSpacingScale(nodeCount) {
    if (!state.spacing.autoScale) return state.spacing.manualScale;
    const raw = Math.max(1, Math.sqrt(nodeCount / SPACING_BASELINE_NODES));
    return state.spacing.unlimited ? raw : Math.min(MAX_SPACING_SCALE, raw);
  }

  // The side length (in grid cells) a roughly-square packed grid of n nodes needs.
  function packedGridCols(n) {
    return Math.max(1, Math.ceil(Math.sqrt(n)));
  }

  // Cell size scales very gently with the spacing scale (sqrt, not linear) -- per-node packing density
  // should track actual node radii, which don't change with node count, not the same multiplier used to
  // widen the ring *between* clusters. Scaling it the same way the ring radius does would compound: a
  // 25,000-node cluster's footprint would grow by the square of the spacing scale instead of linearly,
  // ballooning the canvas far past what's needed just to avoid nodes overlapping each other.
  function packedCellSize(scale) {
    return GRID_PACK_CELL_SIZE * Math.sqrt(scale);
  }

  // Half-diagonal of the square grid packNodesIntoGrid would lay n nodes out into, at this spacing
  // scale -- i.e. how far a cluster's own packed footprint reaches from its anchor.
  function clusterFootprintRadius(n, scale) {
    if (n <= 0) return 0;
    const cellSize = packedCellSize(scale);
    const cols = packedGridCols(n);
    const rows = Math.max(1, Math.ceil(n / cols));
    return Math.hypot(cols, rows) * cellSize * 0.5;
  }

  // A center-outward square spiral: (0,0), (1,0), (1,1), (0,1), (-1,1), (-1,0), (-1,-1), (0,-1), (1,-1),
  // (2,-1), ... Used so the *order* nodes are handed to packNodesIntoGrid in becomes their proximity to
  // the cluster anchor -- first in, closest to center.
  function spiralGridOffsets(n) {
    const offsets = [];
    let col = 0;
    let row = 0;
    let dcol = 1;
    let drow = 0;
    let segmentLength = 1;
    let segmentPassed = 0;
    let turns = 0;
    for (let i = 0; i < n; i++) {
      offsets.push({col, row});
      col += dcol;
      row += drow;
      segmentPassed += 1;
      if (segmentPassed === segmentLength) {
        segmentPassed = 0;
        const nextDcol = -drow;
        const nextDrow = dcol;
        dcol = nextDcol;
        drow = nextDrow;
        turns += 1;
        if (turns % 2 === 0) segmentLength += 1;
      }
    }
    return offsets;
  }

  // Deterministically lays nodes out in a packed grid centered on anchor, instead of relying on
  // pairwise repulsion to slowly diffuse them apart -- avoids overlap by construction, independent of
  // how many physics iterations follow. A little jitter keeps it from reading as too mechanical without
  // reintroducing the near-coincident-start problem a fully random scatter would cause.
  //
  // Nodes are filled into the grid highest-degree first, via a center-out spiral rather than row-major
  // order: the most heavily-linked ("costly to leave unsorted") nodes land closest to the cluster
  // anchor, and nodes with no edges at all -- which sort to the back since their degree is 0 -- land
  // together in the outer ring, next to each other and away from the connected core, instead of
  // arbitrarily interspersed throughout.
  function packNodesIntoGrid(nodes, anchor, scale) {
    const n = nodes.length;
    if (!n) return;
    const cellSize = packedCellSize(scale);
    const ordered = nodes.slice().sort((a, b) => (b.degree || 0) - (a.degree || 0));
    const offsets = spiralGridOffsets(n);
    ordered.forEach((node, i) => {
      const {col, row} = offsets[i];
      node.x = anchor.x + col * cellSize + (Math.random() - 0.5) * cellSize * 0.5;
      node.y = anchor.y + row * cellSize + (Math.random() - 0.5) * cellSize * 0.5;
    });
  }

  // maxClusterSize (packed-seed scopes only) grows the ring radius so the single largest cluster's own
  // packed footprint can't spill into a neighboring anchor's territory -- a shared total-node-count-based
  // radius left no room for a 25,000-node "file" cluster sitting next to a few-hundred-node "module"
  // cluster on the same ring. Also called (without maxClusterSize) whenever groupByKind/groupByOwner
  // change live, since clusterKey's key shape depends on those toggles and the anchor map must be
  // rebuilt to match before clusterAnchor can look anything up correctly.
  function rebuildClusterAnchors(scale, maxClusterSize) {
    const keys = clusterKeys();
    let radius = BASE_CLUSTER_RADIUS * scale;
    if (maxClusterSize) {
      const footprint = clusterFootprintRadius(maxClusterSize, scale);
      // Chord length between adjacent anchors on the ring is 2*radius*sin(pi/N); solving for the
      // radius that keeps that chord comfortably larger than twice the footprint keeps neighboring
      // clusters from overlapping even when one of them is enormous.
      const neighborGap = 2 * Math.sin(Math.PI / keys.length);
      radius = Math.max(radius, (footprint * 2.2) / neighborGap);
    }
    state.clusterAnchors = new Map(keys.map((key, index) => {
      const angle = (index / keys.length) * Math.PI * 2;
      return [key, {x: Math.cos(angle) * radius, y: Math.sin(angle) * radius}];
    }));
  }

  function clusterAnchor(node) {
    return state.clusterAnchors.get(clusterKey(node)) || {x: 0, y: 0};
  }

  // The initial settle always runs for any scope small enough not to use deterministic packing,
  // regardless of physics mode -- that's the layout itself, not what this decides. This governs what
  // happens *after* that settle: whether the scope stays gently, continuously in motion (an
  // Obsidian-style always-slightly-alive graph) and whether dragging a node reheats its neighbors,
  // versus freezing solid once settled and only moving the one node you directly drag. 'off' never
  // does either, 'on' always does, 'auto' does only under the node-count threshold below (a real
  // performance consideration once a scope reaches a few thousand nodes).
  function resolveLivePhysics(nodeCount) {
    if (state.physicsMode === 'on') return nodeCount > 0;
    if (state.physicsMode === 'off') return false;
    return nodeCount > 0 && nodeCount <= state.livePhysicsThreshold;
  }

  // Custom d3-force forces: each is a factory returning a function(alpha) that mutates node.vx/vy (the
  // shape d3-force expects of any force, built-in or custom), plus an initialize(nodes) hook d3 calls
  // whenever the node set changes. These read state.forces live on every tick rather than capturing a
  // value once, so a slider drag takes effect immediately without needing to touch the simulation object.

  function createClusterForce() {
    let nodes = [];
    function force(alpha) {
      // Focus mode is a distinct organizing scheme (rings by hop-distance from one node, see
      // createFocusForce) -- letting kind/owner clustering keep pulling at the same time would just
      // fight it over where every node belongs.
      if (state.focus.enabled) return;
      if (!state.groupByKind && !state.groupByOwner) return;
      const strength = state.forces.clusterStrength;
      if (!strength) return;
      for (const node of nodes) {
        if (node.fx != null) continue;
        const anchor = clusterAnchor(node);
        node.vx += (anchor.x - node.x) * strength * alpha;
        node.vy += (anchor.y - node.y) * strength * alpha;
      }
    }
    force.initialize = (_nodes) => { nodes = _nodes; };
    return force;
  }

  // There is deliberately no hard boundary/canvas-radius clamp -- with this many nodes, the graph should
  // be free to spread as far as the forces actually dictate. The one real risk that leaves unaddressed is
  // a degree-0 ("no friends") node: everything else has a link force reeling it back toward at least one
  // neighbor, but an unconnected node only has this center pull holding it in place against repulsion, so
  // it gets extra pull strength (state.forces.isolatedPull) rather than drifting off alone.
  // Connected structure only ever gets a uniform whole-graph translation (based on how far the
  // *centroid* of connected nodes has drifted from the origin), not an individual pull toward (0,0).
  // A per-node pull toward the origin is what previously compressed any tree/branching structure into a
  // dense circular blob at equilibrium -- pairwise repulsion balanced against a uniform inward pull on
  // every node always settles into a filled disc, no matter how far out a branch "wants" to extend. A
  // rigid shift of the whole layout keeps it roughly on-screen without fighting local structure at all.
  // Degree-0 ("no friends") nodes are the exception: nothing else reels them back toward anything (no
  // link force to any neighbor), so they still get their own, stronger, individually-targeted pull --
  // otherwise they're the one case that can drift arbitrarily far under repulsion alone.
  function createCenterPullForce() {
    let nodes = [];
    function force(alpha) {
      const strength = state.forces.center;
      if (!strength) return;
      let sumX = 0;
      let sumY = 0;
      let connectedCount = 0;
      for (const node of nodes) {
        if (node.degree === 0) continue;
        sumX += node.x;
        sumY += node.y;
        connectedCount += 1;
      }
      if (connectedCount > 0) {
        const dx = -(sumX / connectedCount) * strength * alpha;
        const dy = -(sumY / connectedCount) * strength * alpha;
        for (const node of nodes) {
          if (node.fx != null) continue;
          node.vx += dx;
          node.vy += dy;
        }
      }
      for (const node of nodes) {
        if (node.fx != null || node.degree !== 0) continue;
        node.vx -= node.x * strength * state.forces.isolatedPull * alpha;
        node.vy -= node.y * strength * state.forces.isolatedPull * alpha;
      }
    }
    force.initialize = (_nodes) => { nodes = _nodes; };
    return force;
  }

  // ---- Focus mode: organize the graph in concentric rings by hop-distance from one selected node ----

  // Plain BFS over state.edges (the full scope, not just currently-visible/filtered edges, so
  // hop-distance reflects real graph topology rather than whatever relation checkboxes happen to be
  // ticked right now). Nodes unreachable from focusNodeId are simply absent from the returned map.
  function computeFocusDistances(focusNodeId) {
    const distances = new Map();
    if (!focusNodeId) return distances;
    const adjacency = new Map();
    for (const edge of state.edges) {
      const sourceId = edge.source.id;
      const targetId = edge.target.id;
      if (!adjacency.has(sourceId)) adjacency.set(sourceId, []);
      if (!adjacency.has(targetId)) adjacency.set(targetId, []);
      adjacency.get(sourceId).push(targetId);
      adjacency.get(targetId).push(sourceId);
    }
    distances.set(focusNodeId, 0);
    const queue = [focusNodeId];
    for (let head = 0; head < queue.length; head++) {
      const current = queue[head];
      const distance = distances.get(current);
      for (const neighborId of (adjacency.get(current) || [])) {
        if (distances.has(neighborId)) continue;
        distances.set(neighborId, distance + 1);
        queue.push(neighborId);
      }
    }
    return distances;
  }

  // Pulls each unfixed node toward a target radius of hopDistance * ringSpacing from the origin --
  // nodes unreachable from the focus node land one ring past the farthest reached node, instead of
  // being placed as if they were direct neighbors. The focus node itself is pinned via fx/fy (see
  // setFocusNode), not moved by this force. Follows the same live-state, no-caching-pitfalls pattern as
  // createClusterForce/createCenterPullForce, deliberately hand-rolled rather than using d3-force's own
  // forceRadial (whose per-node radius accessor is cached at initialize()-time and would need explicit
  // re-triggering on every focus change).
  function createFocusForce() {
    let nodes = [];
    function force(alpha) {
      if (!state.focus.enabled || !state.focus.nodeId) return;
      let maxDistance = 0;
      for (const value of state.focus.distances.values()) maxDistance = Math.max(maxDistance, value);
      const outerRadius = (maxDistance + 2) * state.focus.ringSpacing;
      for (const node of nodes) {
        if (node.fx != null) continue;
        const distance = state.focus.distances.get(node.id);
        const targetRadius = Number.isFinite(distance) ? distance * state.focus.ringSpacing : outerRadius;
        const currentRadius = Math.hypot(node.x, node.y);
        if (currentRadius < 1e-6) continue; // avoid a divide-by-zero for a node sitting exactly on the origin
        const pull = (targetRadius - currentRadius) / currentRadius * 0.15 * alpha;
        node.vx += node.x * pull;
        node.vy += node.y * pull;
      }
    }
    force.initialize = (_nodes) => { nodes = _nodes; };
    return force;
  }

  // Changes which node focus mode organizes around (or turns focus on/off) -- unpins the previous focus
  // node, recomputes BFS distances from the new one, pins it at the origin (everything else's target
  // radius is relative to that point), and reheats the simulation in place so the existing layout
  // reflows into rings instead of restarting from a fresh seed.
  function setFocusNode(nodeId) {
    if (state.focus.nodeId && state.focus.nodeId !== nodeId) {
      const previous = state.nodeById.get(state.focus.nodeId);
      if (previous) { previous.fx = null; previous.fy = null; }
    }
    state.focus.nodeId = nodeId;
    state.focus.distances = computeFocusDistances(nodeId);
    const focusNode = state.nodeById.get(nodeId);
    if (focusNode) {
      focusNode.x = 0;
      focusNode.y = 0;
      focusNode.fx = 0;
      focusNode.fy = 0;
    }
    nudgeSimulation();
  }

  function clearFocus() {
    if (state.focus.nodeId) {
      const previous = state.nodeById.get(state.focus.nodeId);
      if (previous) { previous.fx = null; previous.fy = null; }
    }
    state.focus.enabled = false;
    state.focus.nodeId = null;
    state.focus.distances = new Map();
    nudgeSimulation();
  }

  // ---- Ego view: ctrl/cmd+click a node to isolate its connected component, recolored by hop-distance
  // tier -- reuses the same BFS Focus mode has (computeFocusDistances), but as a filter (hide everything
  // unreachable), not a layout reorganization. ----

  function setEgoFilter(nodeId) {
    state.egoFilter.enabled = true;
    state.egoFilter.nodeId = nodeId;
    state.egoFilter.distances = computeFocusDistances(nodeId);
    applyFilters();
    renderEgoStatus();
  }

  function clearEgoFilter() {
    if (!state.egoFilter.enabled) return;
    state.egoFilter.enabled = false;
    state.egoFilter.nodeId = null;
    state.egoFilter.distances = new Map();
    applyFilters();
    renderEgoStatus();
  }

  function renderEgoStatus() {
    if (typeof document === 'undefined') return;
    const status = document.getElementById('ego-filter-status');
    if (!status) return;
    if (!state.egoFilter.enabled) {
      status.textContent = '';
      return;
    }
    const node = state.nodeById.get(state.egoFilter.nodeId);
    status.textContent = node ? ('Isolated: ' + nodeLabel(node)) : '';
  }

  // forceManyBody/forceLink cache the strength/distance they were configured with -- unlike the custom
  // forces above, they don't re-read state.forces on their own, so a slider change has to explicitly
  // push the new value back into them. Safe to call any time; a no-op if no simulation is running.
  function syncForcesToSimulation() {
    if (!state.forceManyBody) return;
    if (state.simulationTuning.chargeByDegree) {
      const factor = state.simulationTuning.chargeByDegreeFactor;
      state.forceManyBody.strength((node) => -state.forces.repulsion * (1 + node.degree * factor));
    } else {
      state.forceManyBody.strength(-state.forces.repulsion);
    }
    state.forceManyBody.theta(state.simulationTuning.theta);
    state.forceLink.distance(state.forces.springLength).strength(state.forces.springStrength);
  }

  // Simulation-wide settings that aren't per-node forces: friction, cooling speed, and whether/how
  // collision resolution runs at all. Takes an explicit sim so createSimulation can call this before
  // state.simulation is assigned by its caller; live slider/checkbox handlers call it with no argument
  // and it falls back to the current state.simulation.
  function syncSimulationTuningToSimulation(sim) {
    const target = sim || state.simulation;
    if (!target) return;
    target.velocityDecay(state.simulationTuning.velocityDecay);
    target.alphaDecay(state.simulationTuning.alphaDecay);
    if (state.simulationTuning.collideEnabled) {
      target.force('collide', d3.forceCollide((node) => (
        node.radius + state.simulationTuning.collidePadding + Math.sqrt(node.degree) * state.simulationTuning.hubCollisionBuffer
      )).strength(state.simulationTuning.collideStrength));
    } else {
      target.force('collide', null);
    }
  }

  function createSimulation(nodes, edges) {
    const sim = d3.forceSimulation(nodes)
      .force('charge', d3.forceManyBody())
      .force('link', d3.forceLink(edges))
      .force('cluster', createClusterForce())
      .force('centerPull', createCenterPullForce())
      .force('focus', createFocusForce());
    state.forceManyBody = sim.force('charge');
    state.forceLink = sim.force('link');
    syncForcesToSimulation();
    syncSimulationTuningToSimulation(sim);
    return sim;
  }

  function stopSimulation() {
    if (state.simulation) {
      state.simulation.stop();
      state.simulation = null;
      state.forceManyBody = null;
      state.forceLink = null;
    }
  }

  // ---- Bridging the physics layer (plain node objects, see buildSimulation) to the rendering layer
  // (a graphology.Graph driving a Sigma WebGL renderer) ----

  function buildGraphologyGraph(nodes, edges) {
    const graphInstance = new graphology.Graph({type: 'directed', multi: true});
    for (const node of nodes) {
      const color = nodeColor(node);
      graphInstance.addNode(node.id, {
        x: node.x,
        y: node.y,
        size: node.radius,
        color,
        // The kind/owner color, kept alongside the live (possibly ego-tier-overridden) `color` -- see
        // syncVisibilityToGraphology -- so restoring the normal look when ego view turns off doesn't
        // need to recompute or look anything up.
        baseColor: color,
        label: nodeLabel(node),
        hidden: !node.visible,
      });
    }
    for (const edge of edges) {
      const color = edgeColor(edge);
      graphInstance.addEdge(edge.source.id, edge.target.id, {
        relation: edge.relation,
        size: edge.relation === 'marker_edit' ? 1.4 : (edge.relation === 'contains' ? 0.6 : 1),
        color,
        baseColor: color,
        hidden: !state.filters.relations.has(edge.relation) || !edge.source.visible || !edge.target.visible,
      });
    }
    return graphInstance;
  }

  // Ego view's hop-distance tier palette lookup -- capped at the last tier for anything further out.
  function egoTierColor(distance) {
    return EGO_TIER_COLORS[Math.min(distance, EGO_TIER_COLORS.length - 1)];
  }

  // Bulk position sync, called once per d3 tick (or once for a deterministic packed-grid placement).
  // graphology's updateEachNodeAttributes emits a single graph-changed event for the whole pass instead
  // of one per node -- with up to LARGE_GRAPH_NODE_THRESHOLD (4000) nodes ticking, per-node
  // setNodeAttribute calls would each pay their own event-emission cost every frame.
  function syncPositionsToGraphology() {
    if (!state.graphology) return;
    state.graphology.updateEachNodeAttributes((id, attr) => {
      const node = state.nodeById.get(id);
      if (node) {
        attr.x = node.x;
        attr.y = node.y;
      }
      return attr;
    }, {attributes: ['x', 'y']});
  }

  function syncVisibilityToGraphology() {
    if (!state.graphology) return;
    const egoOn = state.egoFilter.enabled;
    state.graphology.updateEachNodeAttributes((id, attr) => {
      const node = state.nodeById.get(id);
      attr.hidden = !(node && node.visible);
      attr.color = egoOn ? egoTierColor(state.egoFilter.distances.get(id) || 0) : attr.baseColor;
      return attr;
    }, {attributes: ['hidden', 'color']});
    state.graphology.updateEachEdgeAttributes((edge, attr, sourceId, targetId, sourceAttr, targetAttr) => {
      attr.hidden = !state.filters.relations.has(attr.relation) || Boolean(sourceAttr.hidden) || Boolean(targetAttr.hidden);
      if (egoOn) {
        const farther = Math.max(state.egoFilter.distances.get(sourceId) || 0, state.egoFilter.distances.get(targetId) || 0);
        attr.color = egoTierColor(farther);
      } else {
        attr.color = attr.baseColor;
      }
      return attr;
    }, {attributes: ['hidden', 'color']});
  }

  const SIGMA_SETTINGS = {
    renderEdgeLabels: false,
    defaultEdgeType: 'line',
    labelRenderedSizeThreshold: 6,
    // Sigma's own default label color is near-black, meant for a light background -- illegible against
    // this app's dark purple canvas. Match the light, muted tone the old Canvas2D label rendering used.
    labelColor: {color: '#f8eaff'},
    minCameraRatio: 0.02,
    maxCameraRatio: 12,
    zIndex: true,
    // Selection/hover only ever touch one or two nodes at a time, so a reducer (which Sigma calls per
    // node every render) stays cheap even at full-catalog scale -- everything else passes through
    // untouched.
    nodeReducer(id, attributes) {
      if (id === state.selectedNodeId) return {...attributes, color: SELECTED_NODE_COLOR, zIndex: 1};
      return attributes;
    },
  };

  // Frames the camera on whatever's currently in the graph. Sigma's camera is normalized to the graph's
  // own bounding box: {x: 0.5, y: 0.5, ratio: 1} is "everything visible, centered" regardless of how many
  // world units the current scope actually spans -- so this single call replaces both the old manual
  // fit-to-active-nodes matrix math AND the old snap-instead-of-smooth-zoom bug, since camera.animate()
  // eases between states instead of jumping.
  function fitView(animated) {
    if (!state.renderer) return;
    const camera = state.renderer.getCamera();
    const target = {x: 0.5, y: 0.5, angle: 0, ratio: 1};
    if (animated) camera.animate(target, {duration: 350});
    else camera.setState(target);
  }

  function refreshSelectionHighlight() {
    if (state.renderer) state.renderer.refresh();
  }

  function attachRendererEvents(renderer) {
    const tooltip = document.getElementById('node-tooltip');
    let lastPointer = {x: 0, y: 0};
    const container = document.getElementById('graph-container');
    if (container) {
      container.addEventListener('mousemove', (event) => {
        const rect = container.getBoundingClientRect();
        lastPointer = {x: event.clientX - rect.left, y: event.clientY - rect.top};
        if (tooltip && !tooltip.hidden) {
          tooltip.style.left = (lastPointer.x + 14) + 'px';
          tooltip.style.top = (lastPointer.y + 14) + 'px';
        }
      });
    }

    renderer.on('enterNode', ({node}) => {
      if (state.draggingNodeId) return;
      const n = state.nodeById.get(node);
      if (!n || !tooltip) return;
      tooltip.textContent = tooltipText(n);
      tooltip.style.left = (lastPointer.x + 14) + 'px';
      tooltip.style.top = (lastPointer.y + 14) + 'px';
      tooltip.hidden = false;
    });
    renderer.on('leaveNode', () => {
      if (tooltip) tooltip.hidden = true;
    });

    renderer.on('clickNode', ({node, event}) => {
      state.selectedNodeId = node;
      renderNodeDetail(state.nodeById.get(node));
      refreshSelectionHighlight();
      if (state.focus.enabled) {
        setFocusNode(node);
        renderFocusStatus();
      }
      const modifierHeld = event && event.original && (event.original.ctrlKey || event.original.metaKey);
      if (modifierHeld) setEgoFilter(node);
    });
    renderer.on('clickStage', () => {
      state.selectedNodeId = null;
      renderNodeDetail(null);
      refreshSelectionHighlight();
      clearEgoFilter();
    });

    // Node dragging: sigma.js's own documented pattern (downNode + the mouse captor's mousemovebody +
    // mouseup). While dragging, the underlying physics node's fx/fy is set too (see the mousemovebody
    // handler below) so a live simulation's tick doesn't fight the drag, and startDragPhysics/
    // stopDragPhysics reheat neighbors exactly as before. The camera is disabled for the duration unless
    // state.allowPanWhileDragging is on -- otherwise Sigma's own default drag-to-pan behavior keeps
    // panning the view at the same time as the node move, which reads as the view "fighting" the drag.
    renderer.on('downNode', ({node}) => {
      state.draggingNodeId = node;
      state.hasDragged = false;
      if (tooltip) tooltip.hidden = true;
      if (!state.allowPanWhileDragging) renderer.getCamera().disable();
      startDragPhysics();
    });
    const mouseCaptor = renderer.getMouseCaptor();
    mouseCaptor.on('mousemovebody', (event) => {
      if (!state.draggingNodeId) return;
      state.hasDragged = true;
      const node = state.nodeById.get(state.draggingNodeId);
      if (!node) return;
      const pos = renderer.viewportToGraph(event);
      node.x = pos.x;
      node.y = pos.y;
      node.fx = pos.x;
      node.fy = pos.y;
      node.vx = 0;
      node.vy = 0;
      node.pinned = true;
      state.graphology.setNodeAttribute(state.draggingNodeId, 'x', pos.x);
      state.graphology.setNodeAttribute(state.draggingNodeId, 'y', pos.y);
      event.preventSigmaDefault();
      event.original.preventDefault();
      event.original.stopPropagation();
    });
    mouseCaptor.on('mouseup', () => {
      if (state.draggingNodeId) {
        stopDragPhysics();
        if (state.hasDragged) nudgeSimulation();
      }
      state.draggingNodeId = null;
      renderer.getCamera().enable();
    });
  }

  // (Re)creates the graphology graph and Sigma renderer for the current state.nodes/state.edges --
  // called whenever the *scope* changes (applyScope), not on every physics tick or filter toggle, so
  // this cost is paid once per scope change rather than once per frame.
  function rebuildRenderer() {
    if (state.renderer) {
      state.renderer.kill();
      state.renderer = null;
    }
    state.graphology = buildGraphologyGraph(state.nodes, state.edges);
    const container = document.getElementById('graph-container');
    if (!container) return;
    // The container's height comes from CSS (.canvas-panel's 75vh), which is normally already resolved
    // by the time a scope change runs this -- but the very first render can occasionally race layout
    // (e.g. a background/not-yet-composited tab). Sigma refuses to construct against a zero-size
    // container, so wait a frame and retry rather than leaving its "container has no height" banner
    // stuck on screen.
    if (container.clientHeight === 0 || container.clientWidth === 0) {
      window.requestAnimationFrame(() => rebuildRenderer());
      return;
    }
    state.renderer = new Sigma(state.graphology, container, SIGMA_SETTINGS);
    attachRendererEvents(state.renderer);
    fitView(false);
  }

  function runSimulation(nodes, edges, onDone) {
    stopSimulation();
    state.livePhysics = resolveLivePhysics(nodes.length);
    // The settle always runs, regardless of scope size or physics mode/threshold -- that's the layout
    // itself, not what state.livePhysics decides (see resolveLivePhysics). For isHugeScope scopes, a good
    // seed is already close to a reasonable layout, so the settle needs far fewer ticks to resolve local
    // overlap/spacing -- see the tick cap below, which bounds wall-clock cost directly instead of waiting
    // on alpha decay that would take far too long at this node count.
    state.simulationDone = false;
    const sim = createSimulation(nodes, edges);
    state.simulation = sim;
    let lastTimestamp = null;
    let ended = false;
    let tickCount = 0;
    function finish() {
      if (ended) return;
      ended = true;
      state.perf.frameMs = 0;
      state.simulationDone = true;
      onDone();
      // Once naturally settled, scopes physics mode/threshold marks as "live" (state.livePhysics) stay
      // gently in motion afterward -- the Obsidian-style always-slightly-alive graph feel.
      if (state.livePhysics && state.simulation === sim) {
        sim.alphaTarget(state.simulationTuning.ambientAlpha).restart();
      }
    }
    sim.on('tick', () => {
      const now = performance.now();
      if (lastTimestamp !== null) state.perf.frameMs = now - lastTimestamp;
      lastTimestamp = now;
      syncPositionsToGraphology();
      tickCount += 1;
      if (state.isHugeScope && tickCount >= MAX_SETTLE_TICKS_HUGE) {
        sim.stop();
        finish();
      }
    });
    sim.on('end', finish);
  }

  function startDragPhysics() {
    // state.livePhysics is the mode/threshold decision of whether dragging is allowed to reheat and push
    // neighbors around at this scope's size -- below it, a dragged node still moves directly, it just
    // doesn't trigger a neighbor-reaction loop.
    if (!state.simulation || !state.livePhysics) return;
    if (state.forceManyBody) {
      const boosted = state.forces.repulsion * state.dragTuning.repulsionMultiplier;
      if (state.simulationTuning.chargeByDegree) {
        const factor = state.simulationTuning.chargeByDegreeFactor;
        state.forceManyBody.strength((node) => -boosted * (1 + node.degree * factor));
      } else {
        state.forceManyBody.strength(-boosted);
      }
    }
    state.simulation.alphaTarget(state.dragTuning.temperature).restart();
  }

  function stopDragPhysics() {
    if (!state.simulation) return;
    syncForcesToSimulation();
    // Releasing the drag hands control back to whatever this scope's resting alphaTarget should be:
    // back to the ambient float for a "live" scope, or down to a real stop otherwise.
    state.simulation.alphaTarget(state.livePhysics ? state.simulationTuning.ambientAlpha : 0);
  }

  // "Nudges" a settled simulation back to life after a setting change (filters, grouping, force
  // sliders, regenerate) instead of rebuilding it from scratch -- positions carry over, only alpha resets.
  function nudgeSimulation() {
    if (!state.simulation) return;
    state.livePhysics = resolveLivePhysics(state.activeNodes.length);
    state.simulation.alpha(Math.max(state.simulation.alpha(), 0.3)).restart();
  }

  // One-shot random velocity kick for every unfixed active node, then reheats alpha -- an escape hatch
  // for a layout that's settled into a lopsided local arrangement, independent of the continuous
  // ambientAlpha motion (that one's gentle and ongoing; this is a deliberate, tunable jolt).
  function jiggleSimulation() {
    if (!state.simulation) return;
    const strength = state.simulationTuning.jiggleStrength;
    for (const node of state.activeNodes) {
      if (node.fx != null) continue;
      node.vx += (Math.random() - 0.5) * strength;
      node.vy += (Math.random() - 0.5) * strength;
    }
    state.simulation.alpha(Math.max(state.simulation.alpha(), 0.5)).restart();
  }

  function nodeMatchesFilters(node) {
    if (!state.filters.kinds.has(node.kind)) return false;
    if ((node.kind === 'module' || node.kind === 'master_file') && node.owner && !state.filters.owners.has(node.owner)) return false;
    if (state.degreeFilter.max !== null && (node.degree < state.degreeFilter.min || node.degree > state.degreeFilter.max)) return false;
    if (state.egoFilter.enabled && node.id !== state.egoFilter.nodeId && !state.egoFilter.distances.has(node.id)) return false;
    if (state.filters.search) {
      const haystack = (node.moduleId || node.path || node.corePath || node.id || '').toLowerCase();
      if (!haystack.includes(state.filters.search)) return false;
    }
    return true;
  }

  // Recomputes the degree range filter's bounds for the current scope and resets the selection to the
  // full range -- a fresh scope means a fresh degree distribution, so preserving a prior numeric
  // selection across an unrelated node set wouldn't mean anything. Called once per applyScope.
  function updateDegreeFilterBounds() {
    let maxDegree = 0;
    for (const node of state.nodes) maxDegree = Math.max(maxDegree, node.degree);
    state.degreeFilter.scopeMax = maxDegree;
    state.degreeFilter.min = 0;
    state.degreeFilter.max = maxDegree;
    renderDegreeFilter();
  }

  // ---- Connections filter: a real dual-handle range slider (two draggable thumbs on one track), not
  // two separate <input type="range"> elements -- there's no native HTML element for this, so it's hand-
  // rolled the same way the explorer's own resizer already is (pointer events, no new dependency). ----

  function degreeFilterElements() {
    if (typeof document === 'undefined') return null;
    const container = document.getElementById('degree-filter');
    if (!container) return null;
    return {
      container,
      track: container.querySelector('.dual-range-track'),
      selected: container.querySelector('.dual-range-selected'),
      thumbMin: document.getElementById('degree-filter-thumb-min'),
      thumbMax: document.getElementById('degree-filter-thumb-max'),
      minLabel: document.getElementById('degree-filter-min-label'),
      maxLabel: document.getElementById('degree-filter-max-label'),
    };
  }

  function renderDegreeFilter() {
    const els = degreeFilterElements();
    if (!els) return;
    const scopeMax = state.degreeFilter.scopeMax || 0;
    const minPct = scopeMax > 0 ? (state.degreeFilter.min / scopeMax) * 100 : 0;
    const maxPct = scopeMax > 0 ? (state.degreeFilter.max / scopeMax) * 100 : 100;
    els.thumbMin.style.left = minPct + '%';
    els.thumbMax.style.left = maxPct + '%';
    els.selected.style.left = minPct + '%';
    els.selected.style.width = Math.max(0, maxPct - minPct) + '%';
    els.minLabel.textContent = String(state.degreeFilter.min);
    els.maxLabel.textContent = String(state.degreeFilter.max);
  }

  function degreeValueFromClientX(clientX, track) {
    const rect = track.getBoundingClientRect();
    const fraction = rect.width > 0 ? Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) : 0;
    return Math.round(fraction * (state.degreeFilter.scopeMax || 0));
  }

  function attachDegreeDualSlider() {
    const els = degreeFilterElements();
    if (!els) return;
    let dragging = null; // 'min' | 'max' | null

    function setValue(which, value) {
      if (which === 'min') state.degreeFilter.min = Math.min(Math.max(0, value), state.degreeFilter.max);
      else state.degreeFilter.max = Math.max(Math.min(state.degreeFilter.scopeMax || 0, value), state.degreeFilter.min);
      renderDegreeFilter();
      applyFilters();
    }

    function onPointerMove(event) {
      if (!dragging) return;
      setValue(dragging, degreeValueFromClientX(event.clientX, els.track));
    }
    function onPointerUp() {
      dragging = null;
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    }
    function startDrag(which) {
      return (event) => {
        event.preventDefault();
        dragging = which;
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp);
      };
    }
    els.thumbMin.addEventListener('pointerdown', startDrag('min'));
    els.thumbMax.addEventListener('pointerdown', startDrag('max'));

    function onKeydown(which) {
      return (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const delta = event.key === 'ArrowLeft' ? -1 : 1;
        setValue(which, state.degreeFilter[which] + delta);
      };
    }
    els.thumbMin.addEventListener('keydown', onKeydown('min'));
    els.thumbMax.addEventListener('keydown', onKeydown('max'));

    // Clicking directly on the track (not a thumb) jumps whichever thumb is nearer to that position.
    els.track.addEventListener('pointerdown', (event) => {
      const value = degreeValueFromClientX(event.clientX, els.track);
      const which = Math.abs(value - state.degreeFilter.min) <= Math.abs(value - state.degreeFilter.max) ? 'min' : 'max';
      setValue(which, value);
    });
  }

  function applyFilters() {
    for (const node of state.nodes) {
      node.visible = nodeMatchesFilters(node);
    }
    state.activeNodes = state.nodes.filter((node) => node.visible);
    state.activeEdges = state.edges.filter((edge) => edge.source.visible && edge.target.visible);
    syncVisibilityToGraphology();
    if (typeof document !== 'undefined') {
      const summary = document.getElementById('scope-summary');
      if (summary) summary.textContent = state.activeNodes.length + ' of ' + state.nodes.length + ' nodes shown';
    }
    renderPhysicsStats();
  }

  // Keeps the kind/owner/relation filter checkboxes in sync with the explorer's Tick all / Untick all --
  // otherwise the checkboxes read as "everything on" while the explorer scope shows nothing (or vice
  // versa), which is exactly the desync this fixes. Doesn't itself call applyFilters(); the caller
  // (Tick all / Untick all) already triggers a full applyScope right after.
  function setAllFilterCheckboxes(enabled) {
    state.filters.kinds = new Set(enabled ? ALL_FILTER_KINDS : []);
    state.filters.owners = new Set(enabled ? ALL_FILTER_OWNERS : []);
    state.filters.relations = new Set(enabled ? ALL_FILTER_RELATIONS : []);
    if (typeof document === 'undefined') return;
    document.querySelectorAll('[data-kind]').forEach((input) => { input.checked = enabled; });
    document.querySelectorAll('[data-owner]').forEach((input) => { input.checked = enabled; });
    document.querySelectorAll('[data-relation]').forEach((input) => { input.checked = enabled; });
  }

  // The "Open in..." menu itself (floating positioning, the three actions) is a shared component -- see
  // webapp/web/open-in-menu.js -- used here and by Lore Editor, instead of two separately-broken
  // reimplementations of the same three actions.
  function renderOpenActions(container, repository, path) {
    window.AphelionOpenInMenu.render(container, {repository, path, onError: setStatus});
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function edgeRelationDetail(edge) {
    if (edge.relation === 'marker_edit') return (edge.editType || 'edit') + (edge.lineNumber ? (' @ line ' + edge.lineNumber) : '');
    if (edge.relation === 'contains') return 'contains';
    if (edge.relation === 'module_reference') return 'references (text mention)';
    if (edge.relation === 'core_reference') return 'references (text mention)';
    return 'master_files mirror';
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
    if (node.kind === 'module') {
      rows.push(['Has readme.md', node.hasReadme ? 'yes' : 'no']);
      if (node.fileCount !== null) rows.push(['DM files', String(node.fileCount)]);
      if (node.totalBytes !== null) rows.push(['Total size', formatBytes(node.totalBytes)]);
    }
    if (node.kind === 'core_file') {
      rows.push(['Marker count', String(node.markerCount)]);
      if (node.lineCount !== null) rows.push(['Lines', String(node.lineCount)]);
      if (node.sizeBytes !== null) rows.push(['Size', formatBytes(node.sizeBytes)]);
    }
    if (node.kind === 'master_file' && node.sizeBytes !== null) rows.push(['Size', formatBytes(node.sizeBytes)]);
    rows.push(['Connections', String(node.degree)]);
    const rowsHtml = rows.map(([label, value]) =>
      '<div class="node-detail-row"><span class="node-detail-label">' + label + ':</span> ' + escapeHtml(String(value)) + '</div>'
    ).join('');
    const connectedEdges = state.edges.filter((edge) => edge.source === node || edge.target === node);
    const edgesHtml = connectedEdges.slice(0, 25).map((edge) => {
      const other = edge.source === node ? edge.target : edge.source;
      const otherLabel = nodeLabel(other);
      const detail = edgeRelationDetail(edge);
      return '<div class="node-detail-row">' + escapeHtml(otherLabel) + ' — <span class="node-detail-label">' + escapeHtml(detail) + '</span></div>';
    }).join('');
    container.innerHTML = rowsHtml + '<h3>Edges (' + connectedEdges.length + ')</h3>' + (edgesHtml || '<p class="metadata">None</p>');
    if (node.path) renderOpenActions(container, 'game', node.path);
  }

  function tooltipText(node) {
    const parts = [nodeLabel(node)];
    if (node.owner) parts.push(node.owner);
    parts.push(node.kind);
    if (node.kind === 'module') {
      parts.push(node.hasReadme ? 'has readme.md' : 'no readme.md');
      if (node.fileCount) parts.push(node.fileCount + ' file(s)');
    }
    if (node.kind === 'core_file') {
      parts.push(node.markerCount + ' marker(s)');
      if (node.lineCount) parts.push(node.lineCount + ' lines');
    }
    parts.push(node.degree + ' connection(s)');
    return parts.join(' · ');
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }

  const SEED_SHAPE_LABELS = {
    spiral: 'Spiral',
    packed: 'Packed grid',
    grid: 'Global grid',
    random: 'Random scatter',
  };

  // Only shows what isn't already visible as a control's own state elsewhere in the panel (Mode's radios
  // already show simulation mode/threshold; the auto-scale-spacing checkbox shows its own computed
  // multiplier via renderSpacingReadout) -- scope size, frame time, and which concrete seed shape "Auto"
  // resolved to, none of which duplicates a control.
  function renderPhysicsStats() {
    if (typeof document === 'undefined') return;
    const container = document.getElementById('physics-stats');
    if (!container) return;
    const frameMs = state.perf.frameMs;
    const frameText = frameMs > 0 ? frameMs.toFixed(1) + ' ms (' + Math.round(1000 / frameMs) + ' fps)' : '—';
    const seedLabel = (SEED_SHAPE_LABELS[state.resolvedSeedShape] || state.resolvedSeedShape) +
      (state.seedShape === 'auto' ? ' (auto)' : '');
    const rows = [
      ['Nodes', state.activeNodes.length + ' visible / ' + state.nodes.length + ' in scope'],
      ['Edges', state.activeEdges.length + ' visible / ' + state.edges.length + ' in scope'],
      ['Initial seed', seedLabel],
      ['Frame time', frameText],
    ];
    container.innerHTML = rows.map(([label, value]) =>
      '<div class="node-detail-row"><span class="node-detail-label">' + label + ':</span> ' + escapeHtml(String(value)) + '</div>'
    ).join('');
    renderSpacingReadout();
    renderFocusStatus();
  }

  // The focused node's own label, shown next to the "Organize around selected node" checkbox --
  // refreshed alongside the other derived readouts rather than needing its own polling.
  function renderFocusStatus() {
    const status = document.getElementById('focus-status');
    if (!status) return;
    if (!state.focus.enabled) {
      status.textContent = '';
    } else if (!state.focus.nodeId) {
      status.textContent = 'Click a node to focus.';
    } else {
      const node = state.nodeById.get(state.focus.nodeId);
      status.textContent = node ? ('Focused: ' + nodeLabel(node)) : '';
    }
  }

  // Computed multiplier live-shown right next to the "Auto-scale spacing" checkbox it belongs to,
  // instead of duplicated in the Performance section.
  function renderSpacingReadout() {
    const readout = document.getElementById('spacing-readout');
    if (readout) readout.textContent = state.spacingScale.toFixed(2) + 'x';
  }

  // ---- Scope: which nodes are currently eligible for simulation ----

  function defaultScopeNodeIds(rawGraph) {
    const ids = new Set();
    for (const node of rawGraph.nodes) {
      if (node.kind === 'module' || node.kind === 'master_file' || node.kind === 'core_file') ids.add(node.id);
    }
    return ids;
  }

  function fullCatalogScopeNodeIds(rawGraph) {
    return new Set(rawGraph.nodes.map((node) => node.id));
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
    // buildSimulation always creates fresh plain node objects (even for the same scope, e.g. on
    // "Regenerate layout") -- any fx/fy pin from a previous focus target lived on the now-discarded old
    // object, not this new one, so it has to be reapplied here. Distances are recomputed too rather than
    // carried over, since a real scope change (not just a regenerate) can genuinely change the topology.
    if (state.focus.enabled && state.focus.nodeId) {
      const focusNode = state.nodeById.get(state.focus.nodeId);
      if (focusNode) {
        focusNode.x = 0;
        focusNode.y = 0;
        focusNode.fx = 0;
        focusNode.fy = 0;
        state.focus.distances = computeFocusDistances(state.focus.nodeId);
      } else {
        // The focused node isn't part of this scope any more -- nothing sensible to organize around.
        clearFocus();
      }
    }
    // Same reasoning as the focus-node handling above: state.egoFilter.distances is keyed by id (not
    // object references) so it survives a same-scope regenerate fine, but a real scope change can
    // genuinely change the topology, and the ego node itself might not even be part of the new scope.
    if (state.egoFilter.enabled) {
      if (state.nodeById.has(state.egoFilter.nodeId)) {
        state.egoFilter.distances = computeFocusDistances(state.egoFilter.nodeId);
      } else {
        clearEgoFilter();
      }
    }
    updateDegreeFilterBounds();
    // rebuildRenderer() must run before applyFilters(): it builds a fresh graphology graph from
    // state.nodes/state.edges (naively unfiltered -- every node.visible is just the true default at this
    // point), and applyFilters()'s syncVisibilityToGraphology() pass is what then sets the correct
    // hidden/color values on THAT graph. Doing it in the other order (as this briefly was) left a
    // freshly-rebuilt graph's colors permanently un-synced whenever ego view was active across a
    // regenerate/scope change, since nothing re-applied the ego-tier override to the new graph afterward.
    rebuildRenderer();
    applyFilters();
    state.simulationDone = false;
    runSimulation(state.activeNodes, state.activeEdges, () => {
      fitView(true);
    });
  }

  // ---- Explorer: VS Code-style tree over the full scanned repository ----

  function isDirectoryNode(nodeId) {
    const node = state.rawNodeById.get(nodeId);
    return Boolean(node && node.kind === 'directory');
  }

  // Directory/file nodes carry a "name" field, but module/master_file/core_file nodes don't (they use
  // module_id/core_path instead) -- falling back straight to "path" for those showed the FULL repo-
  // relative path on every row instead of just that entry's own segment, which is what made every
  // module row in the explorer look like an identical, ellipsis-truncated "modular_nova/mod…".
  function nodeBaseName(node) {
    if (!node) return '';
    if (node.name) return node.name;
    if (node.module_id) return node.module_id;
    if (node.path) return node.path.slice(node.path.lastIndexOf('/') + 1);
    return node.id;
  }

  function explorerChildren(nodeId, keepSet) {
    const ids = state.childrenByParent.get(nodeId) || [];
    const filtered = keepSet ? ids.filter((id) => keepSet.has(id)) : ids.slice();
    return filtered.sort((a, b) => {
      const aIsDir = isDirectoryNode(a);
      const bIsDir = isDirectoryNode(b);
      if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
      const na = state.rawNodeById.get(a);
      const nb = state.rawNodeById.get(b);
      return nodeBaseName(na).localeCompare(nodeBaseName(nb));
    });
  }

  // A chain of directories that each contain exactly one subdirectory and nothing else renders as a
  // single "a/b/c" row instead of three near-empty-looking nested rows, matching VS Code's Explorer.
  // Walks against the same (possibly search-filtered) child list being rendered, so an active filter
  // that breaks a chain (e.g. only "c" matches) doesn't get compressed away.
  function directoryChainLabel(nodeId, keepSet) {
    const node = state.rawNodeById.get(nodeId);
    const labels = [node ? nodeBaseName(node) : nodeId];
    let currentId = nodeId;
    for (;;) {
      const children = explorerChildren(currentId, keepSet);
      if (children.length !== 1 || !isDirectoryNode(children[0])) break;
      currentId = children[0];
      const childNode = state.rawNodeById.get(currentId);
      labels.push(nodeBaseName(childNode));
    }
    return {finalId: currentId, label: labels.join('/')};
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
    const rawNode = state.rawNodeById.get(nodeId);
    const wrapper = document.createElement('div');
    if (!rawNode) return wrapper;

    // Directories compress into their deepest single-child descendant (see directoryChainLabel); the
    // row's identity, checkbox, and expand state all key off that deepest id, matching what the
    // compressed label visually represents. The root sentinel is never compressed, so it always shows
    // as its own row even when the checkout has a single top-level tracked directory.
    let displayId = nodeId;
    let displayLabel = nodeBaseName(rawNode);
    if (rawNode.kind === 'directory' && nodeId !== ROOT_DIR_ID) {
      const chain = directoryChainLabel(nodeId, keepSet);
      displayId = chain.finalId;
      displayLabel = chain.label;
    }
    const displayNode = state.rawNodeById.get(displayId) || rawNode;

    const children = explorerChildren(displayId, keepSet);
    const isDirectory = displayNode.kind === 'directory';
    const isExpandable = children.length > 0;
    const isExpanded = keepSet !== null || state.explorer.expanded.has(displayId);

    const row = document.createElement('div');
    row.className = 'explorer-row';
    row.style.paddingLeft = (depth * 0.9) + 'em';
    row.dataset.id = displayId;

    const toggle = document.createElement('span');
    toggle.className = 'explorer-toggle' + (isExpandable ? '' : ' empty');
    toggle.textContent = isExpandable ? (isExpanded ? '▾' : '▸') : '';
    row.appendChild(toggle);

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.scope.has(displayId);
    checkbox.title = 'Show this ' + (isDirectory ? 'folder' : 'file') + ' on the canvas';
    row.appendChild(checkbox);

    const label = document.createElement('span');
    label.className = 'explorer-label';
    label.textContent = displayLabel;
    label.title = displayNode.path || displayId;
    row.appendChild(label);
    if (isDirectory && !isExpandable) {
      const emptyNote = document.createElement('span');
      emptyNote.className = 'explorer-empty-note';
      emptyNote.textContent = '(empty)';
      row.appendChild(emptyNote);
    }
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
      const expand = !state.explorer.expanded.has(displayId);
      if (expand) {
        state.explorer.expanded.add(displayId);
        renderChildrenIfNeeded();
      } else {
        state.explorer.expanded.delete(displayId);
      }
      childrenContainer.hidden = !expand;
      toggle.textContent = expand ? '▾' : '▸';
      autoFitExplorerWidth();
    };
    toggle.addEventListener('click', toggleExpand);
    label.addEventListener('click', toggleExpand);
    checkbox.addEventListener('click', (event) => event.stopPropagation());
    checkbox.addEventListener('change', () => setSubtreeScope(displayId, checkbox.checked));

    return wrapper;
  }

  const EXPLORER_MIN_WIDTH = 160;
  const EXPLORER_MAX_WIDTH = 640;
  const EXPLORER_ROW_CHROME_WIDTH = 46; // toggle + checkbox + gaps, outside the label text itself

  function setExplorerWidth(pixels) {
    const clamped = Math.max(EXPLORER_MIN_WIDTH, Math.min(EXPLORER_MAX_WIDTH, pixels));
    const layout = document.querySelector('.graph-layout');
    if (layout) layout.style.setProperty('--explorer-width', clamped + 'px');
  }

  let explorerMeasureSpan = null;

  // A label's own scrollWidth can't be trusted for this: .explorer-label already has overflow:hidden +
  // ellipsis, so once the column is narrow, the *rendered* row reports a small scrollWidth regardless
  // of how long the real name is -- exactly backwards for deciding how wide the column needs to be.
  // Measuring the text in an offscreen span (matching the label's own font) sidesteps that entirely.
  function measureTextWidth(text, font) {
    if (!explorerMeasureSpan) {
      explorerMeasureSpan = document.createElement('span');
      explorerMeasureSpan.style.position = 'absolute';
      explorerMeasureSpan.style.visibility = 'hidden';
      explorerMeasureSpan.style.whiteSpace = 'nowrap';
      explorerMeasureSpan.style.left = '-9999px';
      explorerMeasureSpan.style.top = '0';
      document.body.appendChild(explorerMeasureSpan);
    }
    explorerMeasureSpan.style.font = font;
    explorerMeasureSpan.textContent = text;
    return explorerMeasureSpan.offsetWidth;
  }

  // Sizes the column to fit the longest currently-visible row (indentation + checkbox/toggle + label
  // text), so a deeply nested or long module name is never clipped -- unless the user has dragged the
  // resizer themselves, in which case their choice sticks until they double-click it to return to auto-fit.
  function autoFitExplorerWidth() {
    if (state.explorer.widthManual) return;
    const container = document.getElementById('explorer-tree');
    if (!container) return;
    let maxWidth = 0;
    container.querySelectorAll('.explorer-row').forEach((row) => {
      if (row.offsetParent === null) return;
      const label = row.querySelector('.explorer-label');
      if (!label) return;
      const rowFontSize = parseFloat(getComputedStyle(row).fontSize) || 13;
      const depthPadding = parseFloat(row.style.paddingLeft || '0') * rowFontSize;
      const textWidth = measureTextWidth(label.textContent, getComputedStyle(label).font);
      maxWidth = Math.max(maxWidth, depthPadding + EXPLORER_ROW_CHROME_WIDTH + textWidth);
    });
    // +48 covers .card's own 1rem (16px) of padding on each side, plus a little slack for a vertical
    // scrollbar so a label sitting right at the edge doesn't end up re-clipped by it.
    if (maxWidth > 0) setExplorerWidth(maxWidth + 48);
  }

  function attachExplorerResizer() {
    const resizer = document.getElementById('explorer-resizer');
    const panel = document.querySelector('.explorer-panel');
    if (!resizer || !panel) return;
    let startX = 0;
    let startWidth = 0;
    function onMove(event) {
      setExplorerWidth(startWidth + (event.clientX - startX));
    }
    function onUp() {
      resizer.classList.remove('is-dragging');
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    resizer.addEventListener('mousedown', (event) => {
      event.preventDefault();
      state.explorer.widthManual = true;
      startX = event.clientX;
      startWidth = panel.getBoundingClientRect().width;
      resizer.classList.add('is-dragging');
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    });
    resizer.addEventListener('dblclick', () => {
      state.explorer.widthManual = false;
      autoFitExplorerWidth();
    });
  }

  function renderExplorer() {
    const container = document.getElementById('explorer-tree');
    if (!container || !state.rawGraph) return;
    const keepSet = computeExplorerKeepSet(state.explorer.filterText);
    container.innerHTML = '';
    if (keepSet && keepSet.size === 0) {
      const empty = document.createElement('p');
      empty.className = 'metadata';
      empty.textContent = 'No files or folders match that filter.';
      container.appendChild(empty);
      return;
    }
    container.appendChild(createExplorerRow(ROOT_DIR_ID, 0, keepSet));
    autoFitExplorerWidth();
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
    const tickAllButton = document.getElementById('explorer-tick-all');
    if (tickAllButton) {
      tickAllButton.addEventListener('click', () => {
        state.explorer.expanded = new Set([ROOT_DIR_ID]);
        setAllFilterCheckboxes(true);
        applyScope(fullCatalogScopeNodeIds(state.rawGraph));
        renderExplorer();
      });
    }
    const untickAllButton = document.getElementById('explorer-untick-all');
    if (untickAllButton) {
      untickAllButton.addEventListener('click', () => {
        setAllFilterCheckboxes(false);
        applyScope(new Set());
        renderExplorer();
      });
    }
    attachExplorerResizer();
  }

  // ---- Shared range-input readout: flanking min/max labels + a live current-value output, applied
  // uniformly to every <input type="range"> instead of writing bespoke markup per slider. Safe to call
  // repeatedly on the same input (e.g. after its min/max attributes change) -- it builds the wrapper once,
  // then just refreshes the labels' text on subsequent calls. ----

  function bindRangeReadout(input) {
    if (!input) return;
    let wrap = input.closest('.range-readout');
    if (!wrap) {
      wrap = document.createElement('span');
      wrap.className = 'range-readout';
      const minLabel = document.createElement('span');
      minLabel.className = 'range-bound range-bound-min';
      const valueLabel = document.createElement('output');
      valueLabel.className = 'range-value';
      const maxLabel = document.createElement('span');
      maxLabel.className = 'range-bound range-bound-max';
      input.after(wrap);
      wrap.append(minLabel, input, valueLabel, maxLabel);
      input.addEventListener('input', () => { valueLabel.textContent = input.value; });
    }
    wrap.querySelector('.range-bound-min').textContent = input.min;
    wrap.querySelector('.range-bound-max').textContent = input.max;
    wrap.querySelector('.range-value').textContent = input.value;
  }

  function bindAllRangeReadouts() {
    document.querySelectorAll('input[type="range"]').forEach(bindRangeReadout);
  }

  // ---- Static controls (filters, physics panel, scan/refresh) ----

  function attachStaticEvents() {
    document.getElementById('scan-button').addEventListener('click', () => runScan().catch((error) => setStatus(error.message)));
    document.getElementById('refresh-button').addEventListener('click', () => loadGraph().catch((error) => setStatus(error.message)));

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
        syncVisibilityToGraphology();
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
        syncForcesToSimulation();
        nudgeSimulation();
      });
    });

    // Simulation-wide tuning (friction, cooling speed, Barnes-Hut approximation, collision, per-node
    // weighting) -- same generic data-attribute pattern as [data-force] above.
    document.querySelectorAll('[data-tuning]').forEach((input) => {
      input.addEventListener('input', () => {
        const key = input.dataset.tuning;
        const value = input.type === 'checkbox' ? input.checked : Number(input.value);
        state.simulationTuning[key] = value;
        syncForcesToSimulation();
        syncSimulationTuningToSimulation();
        // ambientAlpha is the resting alphaTarget a live scope's *already-settled* simulation sits at --
        // re-apply it directly so a scope currently in that resting phase feels the change immediately,
        // rather than only picking it up the next time something else re-triggers alphaTarget (a full
        // settle finishing, or a mode/threshold change).
        if (key === 'ambientAlpha' && state.simulation && state.livePhysics) {
          state.simulation.alphaTarget(value).restart();
        } else {
          nudgeSimulation();
        }
      });
    });

    document.querySelectorAll('[data-drag]').forEach((input) => {
      input.addEventListener('input', () => {
        state.dragTuning[input.dataset.drag] = Number(input.value);
      });
    });

    // Toggling either grouping axis changes the shape of clusterKey's own output, so the anchor ring has
    // to be rebuilt to match before the live cluster force can look anything up correctly -- see
    // rebuildClusterAnchors's own comment.
    const groupByKindInput = document.getElementById('group-by-kind');
    if (groupByKindInput) {
      groupByKindInput.addEventListener('change', () => {
        state.groupByKind = groupByKindInput.checked;
        rebuildClusterAnchors(state.spacingScale);
        nudgeSimulation();
      });
    }
    const groupByOwnerInput = document.getElementById('group-by-owner');
    if (groupByOwnerInput) {
      groupByOwnerInput.addEventListener('change', () => {
        state.groupByOwner = groupByOwnerInput.checked;
        rebuildClusterAnchors(state.spacingScale);
        nudgeSimulation();
      });
    }

    attachDegreeDualSlider();

    const autoScaleSpacingInput = document.getElementById('auto-scale-spacing');
    const spacingScaleInput = document.getElementById('spacing-scale');
    if (autoScaleSpacingInput && spacingScaleInput) {
      autoScaleSpacingInput.addEventListener('change', () => {
        state.spacing.autoScale = autoScaleSpacingInput.checked;
        spacingScaleInput.disabled = state.spacing.autoScale;
        // Spacing affects cluster anchors and the initial spawn layout, not just live forces -- a full
        // regenerate (not just a nudge) is needed for it to actually take effect.
        applyScope(new Set(state.scope));
      });
      spacingScaleInput.addEventListener('change', () => {
        state.spacing.manualScale = Number(spacingScaleInput.value);
        if (!state.spacing.autoScale) applyScope(new Set(state.scope));
      });
    }
    const unlimitedSpacingInput = document.getElementById('unlimited-spacing');
    if (unlimitedSpacingInput && spacingScaleInput) {
      unlimitedSpacingInput.addEventListener('change', () => {
        state.spacing.unlimited = unlimitedSpacingInput.checked;
        // The manual slider's own HTML bound, not just the auto-mode formula's cap -- otherwise
        // "unlimited" would still leave the slider itself unable to be dragged past 1000.
        spacingScaleInput.max = state.spacing.unlimited ? '100000' : '1000';
        bindRangeReadout(spacingScaleInput);
        applyScope(new Set(state.scope));
      });
    }

    const seedShapeInput = document.getElementById('seed-shape');
    if (seedShapeInput) {
      seedShapeInput.addEventListener('change', () => {
        state.seedShape = seedShapeInput.value;
        applyScope(new Set(state.scope));
      });
    }

    const focusEnabledInput = document.getElementById('focus-enabled');
    if (focusEnabledInput) {
      focusEnabledInput.addEventListener('change', () => {
        if (focusEnabledInput.checked) {
          state.focus.enabled = true;
          renderFocusStatus();
        } else {
          clearFocus();
          renderFocusStatus();
        }
      });
    }
    document.querySelectorAll('[data-focus]').forEach((input) => {
      input.addEventListener('input', () => {
        state.focus[input.dataset.focus] = Number(input.value);
        nudgeSimulation();
      });
    });

    const regenerateButton = document.getElementById('regenerate-layout-button');
    if (regenerateButton) {
      regenerateButton.addEventListener('click', () => applyScope(new Set(state.scope)));
    }
    const resetPhysicsButton = document.getElementById('reset-physics-button');
    if (resetPhysicsButton) {
      resetPhysicsButton.addEventListener('click', () => resetPhysicsToDefaults());
    }
    const jiggleButton = document.getElementById('jiggle-simulation-button');
    if (jiggleButton) {
      jiggleButton.addEventListener('click', () => jiggleSimulation());
    }
    const allowPanInput = document.getElementById('allow-pan-while-dragging');
    if (allowPanInput) {
      allowPanInput.addEventListener('change', () => {
        state.allowPanWhileDragging = allowPanInput.checked;
      });
    }
    const clearEgoFilterButton = document.getElementById('clear-ego-filter-button');
    if (clearEgoFilterButton) {
      clearEgoFilterButton.addEventListener('click', () => clearEgoFilter());
    }
    document.querySelectorAll('input[name="physics-mode"]').forEach((input) => {
      input.addEventListener('change', () => {
        if (!input.checked) return;
        state.physicsMode = input.value;
        state.livePhysics = resolveLivePhysics(state.activeNodes.length);
        if (state.simulation) {
          if (state.livePhysics) {
            // Switched into a mode/threshold that keeps this scope alive -- start the ambient float
            // immediately rather than waiting for the next full regenerate.
            state.simulation.alphaTarget(state.simulationTuning.ambientAlpha).restart();
          } else {
            // Switched out of it -- let alpha decay back to a real stop instead of floating forever.
            state.simulation.alphaTarget(0);
          }
        }
        renderPhysicsStats();
      });
    });
    const thresholdInput = document.getElementById('physics-threshold');
    if (thresholdInput) {
      thresholdInput.addEventListener('change', () => {
        const value = Number(thresholdInput.value);
        if (!Number.isFinite(value) || value < 1) return;
        state.livePhysicsThreshold = value;
        if (state.physicsMode === 'auto') {
          state.livePhysics = resolveLivePhysics(state.activeNodes.length);
          if (state.simulation) {
            if (state.livePhysics) state.simulation.alphaTarget(state.simulationTuning.ambientAlpha).restart();
            else state.simulation.alphaTarget(0);
          }
          renderPhysicsStats();
        }
      });
    }

    attachExplorerEvents();
    bindAllRangeReadouts();
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
      counts.marker_count + ' markers (' + counts.unresolved_marker_count + ' unresolved — see Modular Debug), ' +
      counts.file_count + ' tracked files across ' + counts.directory_count + ' directories, ' +
      (counts.reference_count || 0) + ' cross-references found.'
    );
    state.explorer.expanded = new Set([ROOT_DIR_ID]);
    renderExplorer();
    applyScope(defaultScopeNodeIds(payload.graph));
  }

  let statsIntervalHandle = null;

  function startStatsInterval() {
    if (statsIntervalHandle !== null) return;
    statsIntervalHandle = window.setInterval(renderPhysicsStats, 500);
  }

  function stopStatsInterval() {
    if (statsIntervalHandle !== null) {
      window.clearInterval(statsIntervalHandle);
      statsIntervalHandle = null;
    }
  }

  function pauseView() {
    // d3's internal timer keeps ticking via requestAnimationFrame even while this tool's tab isn't the
    // visible one in the SPA shell -- stop it outright rather than just cancelling a frame handle.
    stopSimulation();
    stopStatsInterval();
  }

  function resumeView() {
    startStatsInterval();
    if (state.nodes.length && !state.simulation) {
      state.simulationDone = false;
      runSimulation(state.activeNodes, state.activeEdges, () => fitView(true));
    }
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('aphelion:tool-visibility', (event) => {
      if (!event.detail || event.detail.tool !== 'graph') return;
      if (event.detail.visible) resumeView();
      else pauseView();
    });
  }

  function init() {
    attachStaticEvents();
    startStatsInterval();
    loadGraph().catch((error) => setStatus(error.message));
  }

  if (typeof document !== 'undefined') {
    init();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      state,
      BASE_CLUSTER_RADIUS,
      MAX_SPACING_SCALE,
      LIVE_PHYSICS_NODE_THRESHOLD,
      MAX_SETTLE_TICKS_HUGE,
      computeSpacingScale,
      rebuildClusterAnchors,
      buildSimulation,
      resolveSeedShape,
      placeSpiralSeed,
      placePackedGridSeed,
      placeGlobalGridSeed,
      placeRandomSeed,
      resolveLivePhysics,
      createClusterForce,
      createCenterPullForce,
      createFocusForce,
      computeFocusDistances,
      setFocusNode,
      clearFocus,
      setEgoFilter,
      clearEgoFilter,
      egoTierColor,
      EGO_TIER_COLORS,
      jiggleSimulation,
      setAllFilterCheckboxes,
      ALL_FILTER_KINDS,
      ALL_FILTER_OWNERS,
      ALL_FILTER_RELATIONS,
      resetPhysicsToDefaults,
      DEFAULT_FORCES,
      DEFAULT_SIMULATION_TUNING,
      nodeMatchesFilters,
      updateDegreeFilterBounds,
      tooltipText,
      defaultScopeNodeIds,
      fullCatalogScopeNodeIds,
      computeExplorerKeepSet,
      collectSubtreeIds,
      isDirectoryNode,
      explorerChildren,
      directoryChainLabel,
      nodeBaseName,
      clusterKey,
      clusterKeys,
      clusterAnchor,
      LARGE_GRAPH_NODE_THRESHOLD,
      packedGridCols,
      packedCellSize,
      clusterFootprintRadius,
      packNodesIntoGrid,
      spiralGridOffsets,
      nodeColor,
      edgeColor,
      nodeLabel,
    };
  }
})();
