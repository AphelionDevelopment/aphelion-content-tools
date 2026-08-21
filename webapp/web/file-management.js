(() => {
  'use strict';

const state = {
  repositories: {tool: null, game: null},
  exportStages: [],
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : {};
  if (!response.ok) throw new Error(payload.error || ('Request failed (' + response.status + ')'));
  return payload;
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function repositoryLabel(repository) {
  return repository === 'game' ? 'Meridian-Rift' : 'Aphelion Content Tools';
}

function renderChangedFileRow(repository, filePath) {
  const row = document.createElement('details');
  row.className = 'changed-file';
  const summary = document.createElement('summary');
  summary.textContent = filePath;
  row.append(summary);
  const diffOutput = document.createElement('pre');
  diffOutput.className = 'tool-output diff-output';
  diffOutput.textContent = 'Loading diff…';
  row.append(diffOutput);
  let loaded = false;
  row.addEventListener('toggle', () => {
    if (!row.open || loaded) return;
    loaded = true;
    requestJson('/api/git/diff?repository=' + encodeURIComponent(repository) + '&path=' + encodeURIComponent(filePath))
      .then((payload) => { diffOutput.textContent = payload.diff || '(no textual diff for this change)'; })
      .catch((error) => { diffOutput.textContent = error.message; loaded = false; });
  });
  return row;
}

function renderRepositoryStatus(repository) {
  const status = state.repositories[repository];
  const container = document.querySelector('#' + repository + '-status');
  container.replaceChildren();

  const summary = document.createElement('p');
  summary.className = status?.dirty ? 'repository-dirty' : 'repository-clean';
  summary.textContent = status
    ? (status.dirty ? 'Changes pending' : 'Clean') + ' · ' + status.branch
    : 'Status unavailable';
  container.append(summary);

  const metaLine = document.createElement('p');
  metaLine.className = 'metadata';
  if (status) {
    const aheadBehind = (status.ahead ? ' · ahead ' + status.ahead : '') + (status.behind ? ' · behind ' + status.behind : '');
    metaLine.textContent = (status.changed_files?.length ? status.changed_files.length + ' changed file(s)' : 'No changed files') + aheadBehind;
    if (status.conflicted) metaLine.textContent += ' · conflicts need attention';
    container.append(metaLine);
  }

  if (status?.changed_files?.length) {
    const fileList = document.createElement('div');
    fileList.className = 'changed-file-list';
    for (const filePath of status.changed_files) {
      fileList.append(renderChangedFileRow(repository, filePath));
    }
    container.append(fileList);
  }
}

async function loadRepositoryStatus() {
  const statuses = await Promise.all(['tool', 'game'].map(async (repository) => [
    repository,
    await requestJson('/api/git/status?repository=' + repository),
  ]));
  for (const [repository, status] of statuses) state.repositories[repository] = status;
  renderRepositoryStatus('tool');
  renderRepositoryStatus('game');
}

async function loadBranches(repository) {
  const payload = await requestJson('/api/git/branches?repository=' + repository);
  const branches = payload.branches || [];
  const select = document.querySelector('#' + repository + '-branch-select');
  select.replaceChildren();
  for (const branch of branches) {
    const option = document.createElement('option');
    option.value = branch;
    option.textContent = branch;
    select.append(option);
  }
  const current = state.repositories[repository]?.branch;
  if (current && branches.includes(current)) select.value = current;
}

async function createRepositoryBranch(repository) {
  const name = document.querySelector('#' + repository + '-branch-name').value.trim();
  if (!name) throw new Error('Enter a branch name first.');
  await requestJson('/api/git/branch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository, name}),
  });
  setText('#' + repository + '-message', 'Created and switched to ' + name + '.');
  document.querySelector('#' + repository + '-branch-name').value = '';
  await Promise.all([loadRepositoryStatus(), loadBranches(repository)]);
}

async function switchRepositoryBranch(repository) {
  const branch = document.querySelector('#' + repository + '-branch-select').value;
  if (!branch) throw new Error('Choose a branch to switch to first.');
  await requestJson('/api/git/switch-branch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository, name: branch}),
  });
  setText('#' + repository + '-message', 'Switched to ' + branch + '.');
  await Promise.all([loadRepositoryStatus(), loadBranches(repository)]);
}

async function commitRepositoryChanges(repository) {
  const status = state.repositories[repository];
  const message = document.querySelector('#' + repository + '-commit-message').value.trim();
  if (!status?.changed_files?.length) throw new Error('No changed files to commit.');
  if (!message) throw new Error('Enter a commit message first.');
  await requestJson('/api/git/commit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository, paths: status.changed_files, message}),
  });
  setText('#' + repository + '-message', 'Committed ' + status.changed_files.length + ' file(s).');
  document.querySelector('#' + repository + '-commit-message').value = '';
  await loadRepositoryStatus();
}

async function openRepositoryInDesktop(repository) {
  await requestJson('/api/git/open', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository}),
  });
  setText('#' + repository + '-message', 'Opened in GitHub Desktop.');
}

function attachRepositoryControls(repository) {
  document.querySelector('#' + repository + '-refresh-button').addEventListener('click', () =>
    Promise.all([loadRepositoryStatus(), loadBranches(repository)]).catch((error) => setText('#' + repository + '-message', error.message)));
  document.querySelector('#' + repository + '-switch-branch-button').addEventListener('click', () =>
    switchRepositoryBranch(repository).catch((error) => setText('#' + repository + '-message', error.message)));
  document.querySelector('#' + repository + '-create-branch-button').addEventListener('click', () =>
    createRepositoryBranch(repository).catch((error) => setText('#' + repository + '-message', error.message)));
  document.querySelector('#' + repository + '-commit-button').addEventListener('click', () =>
    commitRepositoryChanges(repository).catch((error) => setText('#' + repository + '-message', error.message)));
  document.querySelector('#' + repository + '-open-desktop-button').addEventListener('click', () =>
    openRepositoryInDesktop(repository).catch((error) => setText('#' + repository + '-message', error.message)));
}

function renderExportStages() {
  // Stage names are UTC timestamps ("YYYYMMDDThhmmssZ-<hash>"), and /api/export/stages returns them
  // sorted ascending by name, so the last entry is always the most recently prepared stage — the
  // picker defaults to it every time the list is (re)rendered, never to whatever was selected before.
  const select = document.querySelector('#export-stage-select');
  select.replaceChildren();
  if (!state.exportStages.length) {
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = 'No prepared stages — prepare one first';
    select.append(empty);
    return;
  }
  for (const stage of state.exportStages) {
    const option = document.createElement('option');
    option.value = stage.stage;
    const manifest = stage.manifest || {};
    option.textContent = stage.stage + ' · ' + (manifest.entry_ids?.length || 0) + ' override(s)';
    select.append(option);
  }
  select.value = state.exportStages[state.exportStages.length - 1].stage;
}

async function loadExportStages() {
  const payload = await requestJson('/api/export/stages');
  state.exportStages = payload.stages || [];
  renderExportStages();
}

async function prepareExport() {
  const payload = await requestJson('/api/export/prepare', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}',
  });
  document.querySelector('#export-output').textContent =
    'Prepared stage ' + payload.stage + '. Review the manifest below, then click Apply to write it into Meridian-Rift.\n\n' +
    JSON.stringify(payload.manifest || payload, null, 2);
  await Promise.all([loadExportStages(), loadRepositoryStatus()]);
}

async function applySelectedExport(force = false) {
  const stage = document.querySelector('#export-stage-select').value;
  if (!stage) throw new Error('Prepare an export before applying one.');
  let payload;
  try {
    payload = await requestJson('/api/export/apply', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({stage, force}),
    });
  } catch (error) {
    if (!force && /uncommitted changes/i.test(error.message)) {
      const proceed = window.confirm(
        'Meridian-Rift has uncommitted changes.\n\n' +
        'Apply the export anyway? This only overwrites the generated lore artifact file — your other ' +
        'uncommitted changes are left alone, but review them before committing.'
      );
      if (proceed) return applySelectedExport(true);
    }
    throw error;
  }
  const desktopNote = payload.opened_in_github_desktop
    ? 'GitHub Desktop opened automatically for the game checkout.'
    : 'Could not open GitHub Desktop automatically' + (payload.github_desktop_error ? (': ' + payload.github_desktop_error) : '.') + ' Open it manually to review, commit, and open a pull request.';
  document.querySelector('#export-output').textContent =
    'Applied ' + payload.artifact + (force ? ' (overrode the uncommitted-changes check)' : '') + '.\n' +
    'Review the game diff above under Meridian-Rift, then commit it locally.\n' + desktopNote;
  await loadRepositoryStatus();
}

function renderTools(tools) {
  const list = document.querySelector('#tool-list');
  list.replaceChildren();
  for (const tool of tools) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.toolId = tool.id;
    button.textContent = tool.label;
    button.title = tool.description || '';
    button.addEventListener('click', () => runTool(tool.id));
    list.append(button);
  }
}

async function pollTool(runId) {
  const payload = await requestJson('/api/tools/runs/' + encodeURIComponent(runId));
  document.querySelector('#tool-output').textContent = payload.output || '';
  setText('#tool-log-path', payload.log_path ? 'Log file: ' + payload.log_path : '');
  if (payload.status === 'queued' || payload.status === 'running') {
    window.setTimeout(() => pollTool(runId).catch((error) => {
      document.querySelector('#tool-output').textContent = error.message;
    }), 750);
    return;
  }
  document.querySelectorAll('[data-tool-id]').forEach((button) => { button.disabled = false; });
  if (payload.status === 'succeeded') {
    await loadRepositoryStatus();
    if (payload.tool_id === 'catalog-refresh') await loadExportStages();
  }
}

async function runTool(toolId) {
  document.querySelectorAll('[data-tool-id]').forEach((button) => { button.disabled = true; });
  document.querySelector('#tool-output').textContent = 'Starting ' + toolId + '…';
  try {
    const payload = await requestJson('/api/tools/' + encodeURIComponent(toolId), {method: 'POST'});
    await pollTool(payload.run_id);
  } catch (error) {
    document.querySelector('#tool-output').textContent = error.message;
    document.querySelectorAll('[data-tool-id]').forEach((button) => { button.disabled = false; });
  }
}

function attachEvents() {
  attachRepositoryControls('tool');
  attachRepositoryControls('game');
  document.querySelector('#prepare-export-button').addEventListener('click', () => {
    document.querySelector('#export-output').textContent = 'Preparing export…';
    prepareExport().catch((error) => { document.querySelector('#export-output').textContent = error.message; });
  });
  document.querySelector('#apply-export-button').addEventListener('click', () => {
    document.querySelector('#export-output').textContent = 'Applying export…';
    applySelectedExport().catch((error) => { document.querySelector('#export-output').textContent = error.message; });
  });
}

async function loadPageData() {
  const tools = await requestJson('/api/tools');
  renderTools(tools.tools || []);
  await loadRepositoryStatus();
  await Promise.all([loadExportStages(), loadBranches('tool'), loadBranches('game')]);
}

function initialize() {
  attachEvents();
  loadPageData().catch((error) => {
    setText('#tool-message', error.message);
    setText('#game-message', error.message);
  });
}

if (typeof document !== 'undefined') {
  initialize();
}

if (typeof window !== 'undefined') {
  window.addEventListener('aphelion:tool-visibility', (event) => {
    if (!event.detail || event.detail.tool !== 'file-management' || !event.detail.visible) return;
    loadRepositoryStatus().then(() => Promise.all([loadBranches('tool'), loadBranches('game')])).catch(() => {});
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {repositoryLabel};
}

})();
