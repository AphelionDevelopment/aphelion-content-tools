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
  graph.state.filters.kinds = new Set(['module', 'master_file', 'core_file', 'directory', 'file']);
  graph.state.filters.owners = new Set(['nova', 'aphelion']);
  graph.state.filters.search = '';
  graph.state.physicsMode = 'auto';
  graph.state.livePhysicsThreshold = graph.LIVE_PHYSICS_NODE_THRESHOLD;
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

test('simulationStep never leaves an unpinned node beyond MAX_RADIUS from the origin', () => {
  resetState();
  const built = graph.buildSimulation({
    nodes: [{id: 'far', kind: 'file', path: 'far.txt'}],
    edges: [],
  });
  const node = built.nodes[0];
  node.x = graph.MAX_RADIUS * 5;
  node.y = 0;
  node.vx = 0;
  node.vy = 0;

  graph.simulationStep(built.nodes, built.edges, 1);

  const distance = Math.hypot(node.x, node.y);
  assert.ok(distance <= graph.MAX_RADIUS + 1e-6, `expected node within MAX_RADIUS, got ${distance}`);
});

test('simulationStep caps a node\'s velocity magnitude at MAX_SPEED', () => {
  resetState();
  graph.state.forces.repulsion = 999999;
  const built = graph.buildSimulation({
    nodes: [{id: 'x', kind: 'file', path: 'x'}, {id: 'y', kind: 'file', path: 'y'}],
    edges: [],
  });
  const [nodeX, nodeY] = built.nodes;
  nodeX.x = 0; nodeX.y = 0;
  nodeY.x = 0.01; nodeY.y = 0;

  graph.simulationStep(built.nodes, built.edges, 1);

  const speed = Math.hypot(nodeX.vx, nodeX.vy);
  assert.ok(speed <= graph.MAX_SPEED + 1e-6, `expected speed within MAX_SPEED, got ${speed}`);
});

test('simulationStep does not move a pinned node', () => {
  resetState();
  const built = graph.buildSimulation({
    nodes: [{id: 'pinned', kind: 'file', path: 'p'}, {id: 'other', kind: 'file', path: 'o'}],
    edges: [],
  });
  const [pinned, other] = built.nodes;
  pinned.pinned = true;
  pinned.x = 10;
  pinned.y = 20;
  other.x = 12;
  other.y = 20;

  graph.simulationStep(built.nodes, built.edges, 1);

  assert.equal(pinned.x, 10);
  assert.equal(pinned.y, 20);
  assert.equal(pinned.vx, 0);
  assert.equal(pinned.vy, 0);
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

test('collectSubtreeIds gathers a node and every descendant', () => {
  graph.state.childrenByParent = new Map([
    ['root', ['a', 'b']],
    ['a', ['a1']],
  ]);

  const out = new Set();
  graph.collectSubtreeIds('root', out);

  assert.deepEqual([...out].sort(), ['a', 'a1', 'b', 'root']);
});
