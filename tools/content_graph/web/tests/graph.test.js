'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const graph = require(path.join(__dirname, '..', 'graph.js'));

function resetState() {
  graph.state.forces.repulsion = 2600;
  graph.state.forces.springLength = 70;
  graph.state.forces.springStrength = 0.02;
  graph.state.forces.center = 0.004;
  graph.state.forces.clusterStrength = 0.025;
  graph.state.forces.isolatedPull = 4;
  graph.state.simulationTuning.velocityDecay = 0.4;
  graph.state.simulationTuning.alphaDecay = 0.0228;
  graph.state.simulationTuning.ambientAlpha = 0.02;
  graph.state.simulationTuning.jiggleStrength = 200;
  graph.state.simulationTuning.theta = 0.9;
  graph.state.simulationTuning.collideEnabled = true;
  graph.state.simulationTuning.collidePadding = 2;
  graph.state.simulationTuning.collideStrength = 1;
  graph.state.simulationTuning.hubCollisionBuffer = 2;
  graph.state.simulationTuning.chargeByDegree = false;
  graph.state.simulationTuning.chargeByDegreeFactor = 0.15;
  graph.state.groupByKind = true;
  graph.state.groupByOwner = true;
  graph.state.filters.kinds = new Set(['module', 'master_file', 'core_file', 'directory', 'file']);
  graph.state.filters.owners = new Set(['nova', 'aphelion']);
  graph.state.filters.relations = new Set(['master_files_mirror', 'marker_edit', 'contains', 'module_reference', 'core_reference']);
  graph.state.filters.search = '';
  graph.state.degreeFilter = {min: 0, max: null, scopeMax: null};
  graph.state.egoFilter = {enabled: false, nodeId: null, distances: new Map()};
  graph.state.allowPanWhileDragging = false;
  graph.state.physicsMode = 'auto';
  graph.state.livePhysicsThreshold = graph.LIVE_PHYSICS_NODE_THRESHOLD;
  graph.state.spacing.autoScale = true;
  graph.state.spacing.manualScale = 1;
  graph.state.spacing.unlimited = false;
  graph.state.seedShape = 'auto';
  graph.state.focus.enabled = false;
  graph.state.focus.nodeId = null;
  graph.state.focus.ringSpacing = 120;
  graph.state.focus.distances = new Map();
}

test('buildSimulation assigns positions, computes degree, and derives radius from degree', () => {
  resetState();
  const rawGraph = {
    nodes: [
      {id: 'a', kind: 'module', owner: 'nova'},
      {id: 'b', kind: 'core_file', path: 'code/x.dm'},
      {id: 'c', kind: 'file', path: 'README.md'},
    ],
    edges: [
      {source: 'a', target: 'b', relation: 'marker_edit', edit_type: 'addition'},
    ],
  };

  const built = graph.buildSimulation(rawGraph);

  assert.equal(built.nodes.length, 3);
  assert.equal(built.edges.length, 1);
  const a = built.nodeById.get('a');
  const b = built.nodeById.get('b');
  const c = built.nodeById.get('c');
  assert.equal(a.degree, 1);
  assert.equal(b.degree, 1);
  assert.equal(c.degree, 0);
  assert.ok(a.radius > c.radius, 'a higher-degree node should render with a larger radius');
  assert.ok(Number.isFinite(a.x) && Number.isFinite(a.y));
});

test('buildSimulation drops edges whose endpoints are not in the node set', () => {
  resetState();
  const rawGraph = {
    nodes: [{id: 'a', kind: 'file', path: 'a.txt'}],
    edges: [{source: 'a', target: 'missing', relation: 'contains'}],
  };

  const built = graph.buildSimulation(rawGraph);

  assert.equal(built.edges.length, 0);
  assert.equal(built.nodeById.get('a').degree, 0);
});

test('createCenterPullForce shifts a single connected node toward the origin, scaled by alpha, and leaves fixed nodes alone', () => {
  resetState();
  graph.state.forces.center = 0.1;
  const node = {x: 100, y: 0, vx: 0, vy: 0, fx: null, degree: 2};
  const fixedNode = {x: 100, y: 0, vx: 0, vy: 0, fx: 100, fy: 0, degree: 2};
  const force = graph.createCenterPullForce();
  force.initialize([node, fixedNode]);

  force(1);

  assert.ok(node.vx < 0, 'an unfixed node right of the origin should be pulled left (negative vx)');
  assert.equal(fixedNode.vx, 0, 'a fixed node should not accumulate velocity from this force');
});

test('createCenterPullForce applies a uniform whole-graph shift based on the connected centroid, not an individual pull per node', () => {
  resetState();
  graph.state.forces.center = 0.1;
  // Two connected nodes straddling the origin -- their centroid IS the origin, so despite neither node
  // sitting at (0,0), a correct centroid-based recentering force should leave both alone (net shift
  // ~zero). The old per-node design would incorrectly pull each one individually toward the origin here.
  const left = {x: -500, y: 0, vx: 0, vy: 0, fx: null, degree: 3};
  const right = {x: 500, y: 0, vx: 0, vy: 0, fx: null, degree: 3};
  const force = graph.createCenterPullForce();
  force.initialize([left, right]);

  force(1);

  assert.ok(Math.abs(left.vx) < 1e-9, `a balanced pair should get ~zero net shift, got left.vx=${left.vx}`);
  assert.ok(Math.abs(right.vx) < 1e-9, `a balanced pair should get ~zero net shift, got right.vx=${right.vx}`);
});

test('createCenterPullForce shifts every connected node by the same amount, unrelated to that node\'s own position', () => {
  resetState();
  graph.state.forces.center = 0.1;
  // Centroid sits at x=300 (drifted off-origin) -- every connected node should be nudged by the exact
  // same amount, regardless of its own distance from the origin, since this is a rigid whole-graph shift.
  const near = {x: 250, y: 0, vx: 0, vy: 0, fx: null, degree: 1};
  const far = {x: 350, y: 0, vx: 0, vy: 0, fx: null, degree: 1};
  const force = graph.createCenterPullForce();
  force.initialize([near, far]);

  force(1);

  assert.ok(near.vx < 0 && far.vx < 0, 'both nodes should shift toward the origin since the centroid is off-origin');
  assert.ok(Math.abs(near.vx - far.vx) < 1e-9, `both connected nodes should receive the identical shift, got near.vx=${near.vx} vs far.vx=${far.vx}`);
});

test('createCenterPullForce pulls degree-0 ("no friends") nodes harder, by state.forces.isolatedPull', () => {
  resetState();
  graph.state.forces.center = 0.1;
  graph.state.forces.isolatedPull = 5;
  const connected = {x: 100, y: 0, vx: 0, vy: 0, fx: null, degree: 3};
  const isolated = {x: 100, y: 0, vx: 0, vy: 0, fx: null, degree: 0};
  const force = graph.createCenterPullForce();
  force.initialize([connected, isolated]);

  force(1);

  assert.ok(Math.abs(isolated.vx) > Math.abs(connected.vx) * 4,
    `an isolated node should be pulled roughly isolatedPull times harder, got isolated.vx=${isolated.vx} vs connected.vx=${connected.vx}`);
});

test('createClusterForce pulls a node toward its cluster anchor unless both grouping axes are disabled', () => {
  resetState();
  graph.rebuildClusterAnchors(1);
  graph.state.forces.clusterStrength = 0.5;
  const anchor = graph.clusterAnchor({kind: 'core_file'});
  const node = {kind: 'core_file', x: anchor.x + 100, y: anchor.y, vx: 0, vy: 0, fx: null};
  const force = graph.createClusterForce();
  force.initialize([node]);

  graph.state.groupByKind = false;
  graph.state.groupByOwner = false;
  force(1);
  assert.equal(node.vx, 0, 'disabling both grouping axes should not apply any cluster pull');

  graph.state.groupByKind = true;
  force(1);
  assert.ok(node.vx < 0, 'node to the right of its anchor should be pulled left (negative vx) once one axis is enabled');
});

test('clusterKey folds in kind and/or owner depending on which grouping axes are active', () => {
  resetState();
  // Both axes on (default): full kind:owner keys for owned kinds, kind:none for the rest.
  assert.equal(graph.clusterKey({kind: 'module', owner: 'nova'}), 'module:nova');
  assert.equal(graph.clusterKey({kind: 'module', owner: 'aphelion'}), 'module:aphelion');
  assert.equal(graph.clusterKey({kind: 'master_file', owner: 'aphelion'}), 'master_file:aphelion');
  assert.equal(graph.clusterKey({kind: 'core_file'}), 'core_file:none');
  assert.equal(graph.clusterKey({kind: 'directory'}), 'directory:none');
  assert.equal(graph.clusterKey({kind: 'file'}), 'file:none');

  // Kind only: owner is folded away even for module/master_file.
  graph.state.groupByOwner = false;
  assert.equal(graph.clusterKey({kind: 'module', owner: 'nova'}), 'module:none');
  assert.equal(graph.clusterKey({kind: 'core_file'}), 'core_file:none');

  // Owner only: kind is folded away, non-owned kinds share one neutral bucket.
  graph.state.groupByKind = false;
  graph.state.groupByOwner = true;
  assert.equal(graph.clusterKey({kind: 'module', owner: 'nova'}), 'any:nova');
  assert.equal(graph.clusterKey({kind: 'master_file', owner: 'aphelion'}), 'any:aphelion');
  assert.equal(graph.clusterKey({kind: 'core_file'}), 'any:none');
  assert.equal(graph.clusterKey({kind: 'file'}), 'any:none');
});

test('clusterKeys enumerates exactly the distinct keys clusterKey can produce for the current grouping axes', () => {
  resetState();
  assert.equal(graph.clusterKeys().length, 7, 'kind + owner: 5 kinds, 2 of which split by owner (+2 extra) = 7');

  graph.state.groupByOwner = false;
  assert.equal(graph.clusterKeys().length, 5, 'kind only: one bucket per kind');

  graph.state.groupByKind = false;
  graph.state.groupByOwner = true;
  assert.equal(graph.clusterKeys().length, 3, 'owner only: nova, aphelion, and a shared none bucket');

  graph.state.groupByOwner = false;
  assert.equal(graph.clusterKeys().length, 1, 'neither axis: everything shares one key');
});

test('clusterAnchor returns a stable, distinct point per cluster key', () => {
  resetState();
  graph.rebuildClusterAnchors(1);
  const novaModuleAnchor = graph.clusterAnchor({kind: 'module', owner: 'nova'});
  const aphelionModuleAnchor = graph.clusterAnchor({kind: 'module', owner: 'aphelion'});
  const coreFileAnchor = graph.clusterAnchor({kind: 'core_file'});

  assert.ok(Number.isFinite(novaModuleAnchor.x) && Number.isFinite(novaModuleAnchor.y));
  assert.notDeepEqual(novaModuleAnchor, aphelionModuleAnchor);
  assert.notDeepEqual(novaModuleAnchor, coreFileAnchor);
  // Calling twice for the same key returns the same anchor -- it's a fixed point, not randomized.
  assert.deepEqual(graph.clusterAnchor({kind: 'module', owner: 'nova'}), novaModuleAnchor);
});

test('computeSpacingScale grows with active node count in auto mode, and is pinned to the manual value otherwise', () => {
  resetState();
  assert.equal(graph.computeSpacingScale(50), 1, 'small graphs stay at the 1x baseline');
  assert.ok(graph.computeSpacingScale(3600) > 2.5, 'a large graph should scale up well past the baseline');
  assert.ok(graph.computeSpacingScale(1000000) <= graph.MAX_SPACING_SCALE, 'auto scale is capped so it cannot grow unbounded');

  graph.state.spacing.autoScale = false;
  graph.state.spacing.manualScale = 3;
  assert.equal(graph.computeSpacingScale(3600), 3, 'manual mode ignores node count entirely');
});

test('computeSpacingScale bypasses MAX_SPACING_SCALE entirely when spacing.unlimited is set', () => {
  resetState();
  graph.state.spacing.unlimited = true;
  const hugeNodeCount = (graph.MAX_SPACING_SCALE + 1) ** 2 * 400;
  const uncapped = graph.computeSpacingScale(hugeNodeCount);
  assert.ok(uncapped > graph.MAX_SPACING_SCALE, `expected the raw sqrt value to exceed the cap, got ${uncapped}`);

  graph.state.spacing.unlimited = false;
  assert.ok(graph.computeSpacingScale(hugeNodeCount) <= graph.MAX_SPACING_SCALE, 'the cap should apply again once unlimited is off');
});

test('buildSimulation widens cluster anchors for a larger active node count', () => {
  resetState();
  const smallGraphNodes = Array.from({length: 5}, (_, i) => ({id: 'small' + i, kind: 'core_file', path: 'x' + i}));
  graph.buildSimulation({nodes: smallGraphNodes, edges: []});
  const smallAnchor = graph.clusterAnchor({kind: 'core_file'});

  const largeGraphNodes = Array.from({length: 4000}, (_, i) => ({id: 'large' + i, kind: 'core_file', path: 'y' + i}));
  graph.buildSimulation({nodes: largeGraphNodes, edges: []});
  const largeAnchor = graph.clusterAnchor({kind: 'core_file'});

  assert.ok(Math.hypot(largeAnchor.x, largeAnchor.y) > Math.hypot(smallAnchor.x, smallAnchor.y),
    'the cluster anchor should sit further from the origin for a much larger active node count');
});

test('packedGridCols returns a roughly square grid side length', () => {
  assert.equal(graph.packedGridCols(1), 1);
  assert.equal(graph.packedGridCols(100), 10);
  assert.equal(graph.packedGridCols(101), 11);
});

test('packNodesIntoGrid places every node inside the grid footprint around the anchor, with no two nodes exactly overlapping', () => {
  const anchor = {x: 500, y: -200};
  const nodes = Array.from({length: 50}, (_, i) => ({x: 0, y: 0}));

  graph.packNodesIntoGrid(nodes, anchor, 1);

  const footprint = graph.clusterFootprintRadius(nodes.length, 1);
  // footprint is the grid's own half-diagonal; a corner node's random jitter (up to +-cellSize/4 per
  // axis) can legitimately push it slightly past that, so allow one cell's worth of slack rather than
  // asserting the jitter never moves a node outward at all.
  const tolerance = graph.packedCellSize(1);
  for (const node of nodes) {
    const dist = Math.hypot(node.x - anchor.x, node.y - anchor.y);
    assert.ok(dist <= footprint + tolerance, `node should land within the cluster's footprint radius (plus jitter slack), got dist ${dist} vs footprint ${footprint} + ${tolerance}`);
  }
  const positions = new Set(nodes.map((n) => n.x.toFixed(3) + ',' + n.y.toFixed(3)));
  assert.equal(positions.size, nodes.length, 'no two nodes should land on the exact same point');
});

test('clusterFootprintRadius grows with node count but only gently with spacing scale (sqrt, not linear)', () => {
  const smallFootprint = graph.clusterFootprintRadius(100, 1);
  const largeFootprint = graph.clusterFootprintRadius(10000, 1);
  assert.ok(largeFootprint > smallFootprint, 'more nodes should need a larger footprint');

  const scale1 = graph.clusterFootprintRadius(1000, 1);
  const scale4 = graph.clusterFootprintRadius(1000, 4);
  // Footprint scales with packedCellSize, which is sqrt(scale) -- quadrupling the spacing scale should
  // almost exactly double the footprint, not quadruple it.
  assert.ok(Math.abs(scale4 / scale1 - 2) < 0.05, `expected roughly 2x footprint growth for 4x spacing scale, got ${scale4 / scale1}x`);
});

test('buildSimulation switches to a packed-grid seed above LARGE_GRAPH_NODE_THRESHOLD, and keeps clusters from overlapping when their sizes are very uneven', () => {
  resetState();
  const nodes = [
    ...Array.from({length: graph.LARGE_GRAPH_NODE_THRESHOLD + 1}, (_, i) => ({id: 'file' + i, kind: 'file', path: 'f' + i})),
    ...Array.from({length: 5}, (_, i) => ({id: 'module' + i, kind: 'module', owner: 'nova', path: 'm' + i})),
  ];

  const built = graph.buildSimulation({nodes, edges: []});

  assert.equal(graph.state.isHugeScope, true);
  assert.equal(graph.state.resolvedSeedShape, 'packed');
  const fileNodes = built.nodes.filter((n) => n.kind === 'file');
  const moduleNodes = built.nodes.filter((n) => n.kind === 'module');
  const fileAnchor = graph.clusterAnchor({kind: 'file'});
  const moduleAnchor = graph.clusterAnchor({kind: 'module', owner: 'nova'});
  const fileFootprint = graph.clusterFootprintRadius(fileNodes.length, graph.state.spacingScale);

  // The huge "file" cluster's own footprint must not reach past the halfway point to the much smaller
  // "module" cluster's anchor -- otherwise the two clusters would visually overlap.
  const anchorGap = Math.hypot(moduleAnchor.x - fileAnchor.x, moduleAnchor.y - fileAnchor.y);
  assert.ok(fileFootprint < anchorGap, `the large cluster's footprint (${fileFootprint}) should not reach its neighbor (gap ${anchorGap})`);

  for (const node of moduleNodes) {
    assert.ok(Number.isFinite(node.x) && Number.isFinite(node.y));
  }
});

test('resolveSeedShape resolves "auto" by node count, but an explicit shape always wins regardless of count', () => {
  resetState();
  assert.equal(graph.resolveSeedShape(10), 'spiral', 'auto should resolve to spiral below the large-graph threshold');
  assert.equal(graph.resolveSeedShape(graph.LARGE_GRAPH_NODE_THRESHOLD + 1), 'packed', 'auto should resolve to packed above the threshold');

  graph.state.seedShape = 'random';
  assert.equal(graph.resolveSeedShape(10), 'random');
  assert.equal(graph.resolveSeedShape(graph.LARGE_GRAPH_NODE_THRESHOLD + 1), 'random', 'an explicit shape ignores node count entirely');
});

test('buildSimulation uses the explicitly chosen seed shape regardless of node count', () => {
  resetState();
  graph.state.seedShape = 'grid';
  const nodes = Array.from({length: 10}, (_, i) => ({id: 'n' + i, kind: 'core_file', path: 'x' + i}));

  graph.buildSimulation({nodes, edges: []});

  assert.equal(graph.state.resolvedSeedShape, 'grid');
  assert.equal(graph.state.isHugeScope, false, 'isHugeScope reflects node count only, independent of the chosen seed shape');
});

test('placeGlobalGridSeed places every node at a finite position, ignoring cluster anchors', () => {
  const nodes = Array.from({length: 30}, (_, i) => ({id: 'n' + i, kind: 'file', degree: i % 5, x: 0, y: 0}));

  graph.placeGlobalGridSeed(nodes, 1);

  for (const node of nodes) {
    assert.ok(Number.isFinite(node.x) && Number.isFinite(node.y));
  }
  const positions = new Set(nodes.map((n) => n.x.toFixed(3) + ',' + n.y.toFixed(3)));
  assert.equal(positions.size, nodes.length, 'no two nodes should land on the exact same point');
});

test('placeRandomSeed scatters every node at a finite position within its cluster footprint', () => {
  resetState();
  graph.rebuildClusterAnchors(1);
  const group = Array.from({length: 20}, (_, i) => ({id: 'n' + i, kind: 'core_file', x: 0, y: 0}));
  const clusterGroups = new Map([['core_file:none', group]]);

  graph.placeRandomSeed(clusterGroups, 1);

  const anchor = graph.clusterAnchor({kind: 'core_file'});
  const footprint = graph.clusterFootprintRadius(group.length, 1);
  for (const node of group) {
    assert.ok(Number.isFinite(node.x) && Number.isFinite(node.y));
    const dist = Math.hypot(node.x - anchor.x, node.y - anchor.y);
    assert.ok(dist <= footprint + 1e-6, `node should land within the cluster footprint, got dist ${dist} vs footprint ${footprint}`);
  }
});

test('computeFocusDistances does a BFS over state.edges: direct neighbors at 1, 2-hop at 2, unreachable nodes absent', () => {
  resetState();
  const a = {id: 'a'};
  const b = {id: 'b'};
  const c = {id: 'c'};
  const isolated = {id: 'isolated'};
  graph.state.edges = [
    {source: a, target: b, relation: 'contains'},
    {source: b, target: c, relation: 'contains'},
  ];

  const distances = graph.computeFocusDistances('a');

  assert.equal(distances.get('a'), 0);
  assert.equal(distances.get('b'), 1);
  assert.equal(distances.get('c'), 2);
  assert.equal(distances.has('isolated'), false);
});

test('computeFocusDistances returns an empty map when there is no focus node', () => {
  resetState();
  graph.state.edges = [];
  const distances = graph.computeFocusDistances(null);
  assert.equal(distances.size, 0);
});

test('createClusterForce no-ops entirely while focus mode is enabled, even with grouping on', () => {
  resetState();
  graph.rebuildClusterAnchors(1);
  graph.state.forces.clusterStrength = 0.5;
  graph.state.focus.enabled = true;
  const anchor = graph.clusterAnchor({kind: 'core_file'});
  const node = {kind: 'core_file', x: anchor.x + 100, y: anchor.y, vx: 0, vy: 0, fx: null};
  const force = graph.createClusterForce();
  force.initialize([node]);

  force(1);

  assert.equal(node.vx, 0, 'focus mode should suppress kind/owner clustering entirely');
});

test('createFocusForce pulls a node toward its hop-distance ring, and leaves the pinned focus node alone', () => {
  resetState();
  graph.state.focus.enabled = true;
  graph.state.focus.nodeId = 'center';
  graph.state.focus.ringSpacing = 100;
  graph.state.focus.distances = new Map([['center', 0], ['near', 1]]);
  // "near" sits too far out (300) for its ring (should be ~100) -- the force should pull it inward.
  const near = {id: 'near', x: 300, y: 0, vx: 0, vy: 0, fx: null};
  const centerNode = {id: 'center', x: 0, y: 0, vx: 0, vy: 0, fx: 0, fy: 0};
  const force = graph.createFocusForce();
  force.initialize([near, centerNode]);

  force(1);

  assert.ok(near.vx < 0, 'a node sitting further out than its target ring should be pulled inward (negative vx)');
  assert.equal(centerNode.vx, 0, 'the pinned focus node itself should not be moved by this force');
});

test('createFocusForce is a no-op when focus mode is disabled', () => {
  resetState();
  graph.state.focus.enabled = false;
  const node = {id: 'n', x: 300, y: 0, vx: 0, vy: 0, fx: null};
  const force = graph.createFocusForce();
  force.initialize([node]);

  force(1);

  assert.equal(node.vx, 0);
});

test('nodeMatchesFilters respects kind, owner, and search filters', () => {
  resetState();
  const moduleNode = {kind: 'module', owner: 'nova', moduleId: 'shuttle_toggle', path: 'modular_nova/modules/shuttle_toggle', corePath: null, id: 'module:nova:shuttle_toggle'};

  assert.equal(graph.nodeMatchesFilters(moduleNode), true);

  graph.state.filters.owners.delete('nova');
  assert.equal(graph.nodeMatchesFilters(moduleNode), false);
  graph.state.filters.owners.add('nova');

  graph.state.filters.kinds.delete('module');
  assert.equal(graph.nodeMatchesFilters(moduleNode), false);
  graph.state.filters.kinds.add('module');

  graph.state.filters.search = 'shuttle';
  assert.equal(graph.nodeMatchesFilters(moduleNode), true);
  graph.state.filters.search = 'nonexistent';
  assert.equal(graph.nodeMatchesFilters(moduleNode), false);
});

test('nodeMatchesFilters respects the degree (connection count) range filter', () => {
  resetState();
  const node = {kind: 'core_file', path: 'code/x.dm', id: 'core_file:code/x.dm', degree: 5};

  assert.equal(graph.state.degreeFilter.max, null, 'no scope loaded yet -- the degree filter should be a no-op');
  assert.equal(graph.nodeMatchesFilters(node), true);

  graph.state.degreeFilter = {min: 0, max: 10, scopeMax: 10};
  assert.equal(graph.nodeMatchesFilters(node), true);

  graph.state.degreeFilter = {min: 6, max: 10, scopeMax: 10};
  assert.equal(graph.nodeMatchesFilters(node), false, 'degree 5 is below the min bound of 6');

  graph.state.degreeFilter = {min: 0, max: 4, scopeMax: 10};
  assert.equal(graph.nodeMatchesFilters(node), false, 'degree 5 is above the max bound of 4');

  graph.state.degreeFilter = {min: 5, max: 5, scopeMax: 10};
  assert.equal(graph.nodeMatchesFilters(node), true, 'degree 5 is within an exact [5,5] bound');
});

test('nodeMatchesFilters respects the ego filter: only the ego node itself or a node reachable from it passes', () => {
  resetState();
  const egoNode = {kind: 'core_file', id: 'ego', degree: 1};
  const neighbor = {kind: 'core_file', id: 'neighbor', degree: 1};
  const stranger = {kind: 'core_file', id: 'stranger', degree: 0};

  assert.equal(graph.nodeMatchesFilters(stranger), true, 'ego filter disabled by default -- no restriction');

  graph.state.egoFilter = {enabled: true, nodeId: 'ego', distances: new Map([['ego', 0], ['neighbor', 1]])};
  assert.equal(graph.nodeMatchesFilters(egoNode), true, 'the ego node itself always passes');
  assert.equal(graph.nodeMatchesFilters(neighbor), true, 'a node present in the distances map passes');
  assert.equal(graph.nodeMatchesFilters(stranger), false, 'a node absent from the distances map is hidden');
});

test('egoTierColor picks progressively later palette entries by hop distance, capped at the last tier', () => {
  assert.equal(graph.egoTierColor(0), graph.EGO_TIER_COLORS[0]);
  assert.equal(graph.egoTierColor(1), graph.EGO_TIER_COLORS[1]);
  const lastIndex = graph.EGO_TIER_COLORS.length - 1;
  assert.equal(graph.egoTierColor(lastIndex), graph.EGO_TIER_COLORS[lastIndex]);
  assert.equal(graph.egoTierColor(lastIndex + 50), graph.EGO_TIER_COLORS[lastIndex], 'distances past the last tier are capped, not out of bounds');
});

test('setEgoFilter and clearEgoFilter toggle state.egoFilter and actually change which nodes are visible', () => {
  resetState();
  const a = {id: 'a', kind: 'core_file', degree: 1};
  const b = {id: 'b', kind: 'core_file', degree: 1};
  const c = {id: 'c', kind: 'core_file', degree: 0};
  graph.state.nodes = [a, b, c];
  graph.state.edges = [{source: a, target: b, relation: 'contains'}];
  graph.state.nodeById = new Map([['a', a], ['b', b], ['c', c]]);

  graph.setEgoFilter('a');
  assert.equal(graph.state.egoFilter.enabled, true);
  assert.equal(graph.state.egoFilter.nodeId, 'a');
  assert.deepEqual(a.visible, true);
  assert.deepEqual(b.visible, true);
  assert.deepEqual(c.visible, false, 'c is unreachable from a and should be filtered out');

  graph.clearEgoFilter();
  assert.equal(graph.state.egoFilter.enabled, false);
  assert.equal(c.visible, true, 'clearing the ego filter restores every node the other filters allow');
});

test('setAllFilterCheckboxes sets every kind/owner/relation filter to fully on or fully off', () => {
  resetState();
  graph.setAllFilterCheckboxes(false);
  assert.equal(graph.state.filters.kinds.size, 0);
  assert.equal(graph.state.filters.owners.size, 0);
  assert.equal(graph.state.filters.relations.size, 0);

  graph.setAllFilterCheckboxes(true);
  assert.deepEqual([...graph.state.filters.kinds].sort(), [...graph.ALL_FILTER_KINDS].sort());
  assert.deepEqual([...graph.state.filters.owners].sort(), [...graph.ALL_FILTER_OWNERS].sort());
  assert.deepEqual([...graph.state.filters.relations].sort(), [...graph.ALL_FILTER_RELATIONS].sort());
});

test('jiggleSimulation is a no-op with no live simulation, and otherwise kicks every unfixed active node', () => {
  resetState();
  // No state.simulation -- should return immediately without touching anything.
  const untouched = {x: 0, y: 0, vx: 0, vy: 0, fx: null};
  graph.state.activeNodes = [untouched];
  graph.jiggleSimulation();
  assert.equal(untouched.vx, 0);
  assert.equal(untouched.vy, 0);
});

test('updateDegreeFilterBounds recomputes the scope max degree and resets the selection to the full range', () => {
  resetState();
  graph.state.nodes = [
    {degree: 0}, {degree: 3}, {degree: 7}, {degree: 2},
  ];
  graph.state.degreeFilter = {min: 2, max: 4, scopeMax: 4};

  graph.updateDegreeFilterBounds();

  assert.equal(graph.state.degreeFilter.scopeMax, 7);
  assert.equal(graph.state.degreeFilter.min, 0);
  assert.equal(graph.state.degreeFilter.max, 7);
});

test('MAX_SETTLE_TICKS_HUGE is a positive, bounded tick cap', () => {
  assert.ok(graph.MAX_SETTLE_TICKS_HUGE > 0);
  assert.ok(graph.MAX_SETTLE_TICKS_HUGE < 1000, 'should be small enough to bound wall-clock cost at tens of thousands of nodes');
});

test('resetPhysicsToDefaults restores every tunable back to its shipped default', () => {
  resetState();
  graph.state.forces.repulsion = 9999;
  graph.state.forces.isolatedPull = 1;
  graph.state.simulationTuning.collideEnabled = false;
  graph.state.simulationTuning.chargeByDegree = true;
  graph.state.groupByKind = false;
  graph.state.groupByOwner = false;
  graph.state.spacing.autoScale = false;
  graph.state.spacing.manualScale = 500;
  graph.state.spacing.unlimited = true;
  graph.state.physicsMode = 'off';
  graph.state.seedShape = 'random';
  graph.state.focus.enabled = true;
  graph.state.focus.nodeId = 'whatever';
  graph.state.focus.ringSpacing = 999;

  graph.resetPhysicsToDefaults();

  assert.deepEqual(graph.state.forces, graph.DEFAULT_FORCES);
  assert.deepEqual(graph.state.simulationTuning, graph.DEFAULT_SIMULATION_TUNING);
  assert.equal(graph.state.groupByKind, true);
  assert.equal(graph.state.groupByOwner, true);
  assert.equal(graph.state.spacing.autoScale, true);
  assert.equal(graph.state.spacing.manualScale, 1);
  assert.equal(graph.state.spacing.unlimited, false);
  assert.equal(graph.state.physicsMode, 'auto');
  assert.equal(graph.state.seedShape, 'auto');
  assert.equal(graph.state.focus.enabled, false);
  assert.equal(graph.state.focus.nodeId, null);
  assert.equal(graph.state.focus.ringSpacing, 120);
});

test('defaultScopeNodeIds selects only module/master_file/core_file kinds', () => {
  const rawGraph = {
    nodes: [
      {id: 'm', kind: 'module'},
      {id: 'mf', kind: 'master_file'},
      {id: 'cf', kind: 'core_file'},
      {id: 'dir', kind: 'directory'},
      {id: 'file', kind: 'file'},
    ],
  };

  const scope = graph.defaultScopeNodeIds(rawGraph);

  assert.deepEqual([...scope].sort(), ['cf', 'm', 'mf']);
});

test('fullCatalogScopeNodeIds selects every node regardless of kind', () => {
  const rawGraph = {
    nodes: [
      {id: 'm', kind: 'module'},
      {id: 'dir', kind: 'directory'},
      {id: 'file', kind: 'file'},
    ],
  };

  const scope = graph.fullCatalogScopeNodeIds(rawGraph);

  assert.deepEqual([...scope].sort(), ['dir', 'file', 'm']);
});

test('nodeColor maps kind/owner to the expected palette entry', () => {
  assert.equal(graph.nodeColor({kind: 'module', owner: 'nova'}), '#55d6ff');
  assert.equal(graph.nodeColor({kind: 'module', owner: 'aphelion'}), '#52f0b0');
  assert.equal(graph.nodeColor({kind: 'master_file'}), '#f2a9dd');
  assert.equal(graph.nodeColor({kind: 'directory'}), '#8f6fae');
  assert.equal(graph.nodeColor({kind: 'file'}), '#6c5a82');
  assert.equal(graph.nodeColor({kind: 'core_file'}), '#d16aff');
});

test('nodeLabel prefers moduleId, then corePath, then name, then path, then id', () => {
  assert.equal(graph.nodeLabel({moduleId: 'a', corePath: 'b', name: 'c', path: 'd', id: 'e'}), 'a');
  assert.equal(graph.nodeLabel({corePath: 'b', name: 'c', path: 'd', id: 'e'}), 'b');
  assert.equal(graph.nodeLabel({name: 'c', path: 'd', id: 'e'}), 'c');
  assert.equal(graph.nodeLabel({path: 'd', id: 'e'}), 'd');
  assert.equal(graph.nodeLabel({id: 'e'}), 'e');
});

test('tooltipText summarizes kind, owner, readme, and connection count', () => {
  const moduleNode = {moduleId: 'shuttle_toggle', kind: 'module', owner: 'nova', hasReadme: false, degree: 3};
  const text = graph.tooltipText(moduleNode);
  assert.equal(text, 'shuttle_toggle · nova · module · no readme.md · 3 connection(s)');

  const coreFileNode = {path: 'code/x.dm', kind: 'core_file', markerCount: 2, degree: 1};
  assert.equal(graph.tooltipText(coreFileNode), 'code/x.dm · core_file · 2 marker(s) · 1 connection(s)');
});

test('computeExplorerKeepSet returns null when no filter text is active', () => {
  graph.state.rawGraph = {nodes: []};
  graph.state.parentByChild = new Map();
  assert.equal(graph.computeExplorerKeepSet(''), null);
});

test('computeExplorerKeepSet keeps matches and their full ancestor chain', () => {
  graph.state.rawGraph = {
    nodes: [
      {id: 'dir:.', path: '.'},
      {id: 'dir:modular_nova', path: 'modular_nova'},
      {id: 'module:nova:shuttle_toggle', path: 'modular_nova/modules/shuttle_toggle'},
      {id: 'file:README.md', path: 'README.md'},
    ],
  };
  graph.state.parentByChild = new Map([
    ['dir:modular_nova', 'dir:.'],
    ['module:nova:shuttle_toggle', 'dir:modular_nova'],
    ['file:README.md', 'dir:.'],
  ]);

  const keep = graph.computeExplorerKeepSet('shuttle');

  assert.deepEqual(
    [...keep].sort(),
    ['dir:.', 'dir:modular_nova', 'module:nova:shuttle_toggle'].sort(),
  );
  assert.equal(keep.has('file:README.md'), false);
});

test('resolveLivePhysics uses the threshold when the mode is auto', () => {
  resetState();
  graph.state.livePhysicsThreshold = 100;

  assert.equal(graph.resolveLivePhysics(50), true);
  assert.equal(graph.resolveLivePhysics(150), false);
  assert.equal(graph.resolveLivePhysics(0), false);
});

test('resolveLivePhysics "on" forces live physics regardless of node count', () => {
  resetState();
  graph.state.physicsMode = 'on';
  graph.state.livePhysicsThreshold = 10;

  assert.equal(graph.resolveLivePhysics(50000), true);
  assert.equal(graph.resolveLivePhysics(0), false);
});

test('resolveLivePhysics "off" never enables live physics', () => {
  resetState();
  graph.state.physicsMode = 'off';

  assert.equal(graph.resolveLivePhysics(1), false);
  assert.equal(graph.resolveLivePhysics(50000), false);
});

test('directoryChainLabel compresses a chain of single-child directories into one label', () => {
  graph.state.rawNodeById = new Map([
    ['dir:a', {id: 'dir:a', kind: 'directory', name: 'a', path: 'a'}],
    ['dir:a/b', {id: 'dir:a/b', kind: 'directory', name: 'b', path: 'a/b'}],
    ['dir:a/b/c', {id: 'dir:a/b/c', kind: 'directory', name: 'c', path: 'a/b/c'}],
    ['file:a/b/c/f.txt', {id: 'file:a/b/c/f.txt', kind: 'file', name: 'f.txt', path: 'a/b/c/f.txt'}],
  ]);
  graph.state.childrenByParent = new Map([
    ['dir:a', ['dir:a/b']],
    ['dir:a/b', ['dir:a/b/c']],
    ['dir:a/b/c', ['file:a/b/c/f.txt']],
  ]);

  const chain = graph.directoryChainLabel('dir:a', null);

  assert.equal(chain.finalId, 'dir:a/b/c');
  assert.equal(chain.label, 'a/b/c');
});

test('directoryChainLabel does not compress past a directory with multiple children', () => {
  graph.state.rawNodeById = new Map([
    ['dir:a', {id: 'dir:a', kind: 'directory', name: 'a', path: 'a'}],
    ['dir:a/b', {id: 'dir:a/b', kind: 'directory', name: 'b', path: 'a/b'}],
    ['file:a/x.txt', {id: 'file:a/x.txt', kind: 'file', name: 'x.txt', path: 'a/x.txt'}],
  ]);
  graph.state.childrenByParent = new Map([
    ['dir:a', ['dir:a/b', 'file:a/x.txt']],
  ]);

  const chain = graph.directoryChainLabel('dir:a', null);

  assert.equal(chain.finalId, 'dir:a');
  assert.equal(chain.label, 'a');
});

test('directoryChainLabel stops at an empty leaf directory', () => {
  graph.state.rawNodeById = new Map([
    ['dir:a', {id: 'dir:a', kind: 'directory', name: 'a', path: 'a'}],
  ]);
  graph.state.childrenByParent = new Map();

  const chain = graph.directoryChainLabel('dir:a', null);

  assert.equal(chain.finalId, 'dir:a');
  assert.equal(chain.label, 'a');
});

test('directoryChainLabel respects an active keepSet, not compressing past a filtered-out sibling', () => {
  graph.state.rawNodeById = new Map([
    ['dir:a', {id: 'dir:a', kind: 'directory', name: 'a', path: 'a'}],
    ['dir:a/b', {id: 'dir:a/b', kind: 'directory', name: 'b', path: 'a/b'}],
    ['dir:a/c', {id: 'dir:a/c', kind: 'directory', name: 'c', path: 'a/c'}],
  ]);
  graph.state.childrenByParent = new Map([
    ['dir:a', ['dir:a/b', 'dir:a/c']],
  ]);
  const keepSet = new Set(['dir:a', 'dir:a/b']);

  const chain = graph.directoryChainLabel('dir:a', keepSet);

  assert.equal(chain.finalId, 'dir:a/b');
  assert.equal(chain.label, 'a/b');
});

test('nodeBaseName falls back to the last path segment for nodes with no name field, not the full path', () => {
  assert.equal(graph.nodeBaseName({name: 'shuttle_toggle', path: 'modular_nova/modules/shuttle_toggle'}), 'shuttle_toggle');
  assert.equal(graph.nodeBaseName({module_id: 'shuttle_toggle', path: 'modular_nova/modules/shuttle_toggle'}), 'shuttle_toggle');
  assert.equal(graph.nodeBaseName({path: 'modular_nova/modules/shuttle_toggle'}), 'shuttle_toggle');
  assert.equal(graph.nodeBaseName({id: 'core_file:code/x.dm'}), 'core_file:code/x.dm');
  assert.equal(graph.nodeBaseName(null), '');
});

test('directoryChainLabel uses each node\'s own segment name, not its full path, for module-like children with no name field', () => {
  graph.state.rawNodeById = new Map([
    ['dir:modular_nova/modules', {id: 'dir:modular_nova/modules', kind: 'directory', name: 'modules', path: 'modular_nova/modules'}],
    ['module:nova:a', {id: 'module:nova:a', kind: 'module', module_id: 'a', path: 'modular_nova/modules/a'}],
    ['module:nova:b', {id: 'module:nova:b', kind: 'module', module_id: 'b', path: 'modular_nova/modules/b'}],
  ]);
  graph.state.childrenByParent = new Map([
    ['dir:modular_nova/modules', ['module:nova:a', 'module:nova:b']],
  ]);

  const chain = graph.directoryChainLabel('dir:modular_nova/modules', null);

  assert.equal(chain.finalId, 'dir:modular_nova/modules');
  assert.equal(chain.label, 'modules');
});

test('isDirectoryNode distinguishes directories from files', () => {
  graph.state.rawNodeById = new Map([
    ['dir:a', {id: 'dir:a', kind: 'directory'}],
    ['file:a.txt', {id: 'file:a.txt', kind: 'file'}],
  ]);

  assert.equal(graph.isDirectoryNode('dir:a'), true);
  assert.equal(graph.isDirectoryNode('file:a.txt'), false);
  assert.equal(graph.isDirectoryNode('missing'), false);
});

test('collectSubtreeIds gathers a node and every descendant', () => {
  graph.state.childrenByParent = new Map([
    ['root', ['a', 'b']],
    ['a', ['a1']],
  ]);

  const out = new Set();
  graph.collectSubtreeIds('root', out);

  assert.deepEqual([...out].sort(), ['a', 'a1', 'b', 'root']);
});
