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
  return repository === 'game' ? 'Meridian-Rift' : 'Lore tools';
}

function renderRepositoryStatus() {
  const list = document.querySelector('#repository-status-list');
  list.replaceChildren();
  for (const repository of ['tool', 'game']) {
    const status = state.repositories[repository];
    const card = document.createElement('article');
    card.className = 'repository-status';
    const heading = document.createElement('strong');
    heading.textContent = repositoryLabel(repository);
    const summary = document.createElement('span');
    summary.className = status?.dirty ? 'repository-dirty' : 'repository-clean';
    summary.textContent = status
      ? (status.dirty ? 'Changes pending' : 'Clean') + ' · ' + status.branch
      : 'Status unavailable';
    const details = document.createElement('p');
    details.className = 'metadata';
    if (status) {
      const aheadBehind = (status.ahead ? ' · ahead ' + status.ahead : '') + (status.behind ? ' · behind ' + status.behind : '');
      details.textContent = (status.changed_files?.length ? status.changed_files.length + ' changed file(s)' : 'No changed files') + aheadBehind;
      if (status.conflicted) details.textContent += ' · conflicts need attention';
    }
    card.append(heading, summary, details);
    list.append(card);
  }
}

async function loadRepositoryStatus() {
  const statuses = await Promise.all(['tool', 'game'].map(async (repository) => [
    repository,
    await requestJson('/api/git/status?repository=' + repository),
  ]));
  for (const [repository, status] of statuses) state.repositories[repository] = status;
  renderRepositoryStatus();
}

async function createRepositoryBranch() {
  const repository = document.querySelector('#git-repository').value;
  const name = document.querySelector('#git-branch-name').value.trim();
  if (!name) throw new Error('Enter a branch name first.');
  await requestJson('/api/git/branch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository, name}),
  });
  setText('#repository-message', 'Created and switched to ' + name + ' in ' + repositoryLabel(repository) + '.');
  await loadRepositoryStatus();
}

async function commitRepositoryChanges() {
  const repository = document.querySelector('#git-repository').value;
  const status = state.repositories[repository];
  const message = document.querySelector('#git-commit-message').value.trim();
  if (!status?.changed_files?.length) throw new Error(repositoryLabel(repository) + ' has no changed files to commit.');
  if (!message) throw new Error('Enter a commit message first.');
  await requestJson('/api/git/commit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository, paths: status.changed_files, message}),
  });
  setText('#repository-message', 'Committed ' + status.changed_files.length + ' file(s) in ' + repositoryLabel(repository) + '.');
  document.querySelector('#git-commit-message').value = '';
  await loadRepositoryStatus();
}

async function openRepositoryInDesktop() {
  const repository = document.querySelector('#git-repository').value;
  await requestJson('/api/git/open', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repository}),
  });
  setText('#repository-message', 'Opened ' + repositoryLabel(repository) + ' in GitHub Desktop.');
}

function renderExportStages() {
  const select = document.querySelector('#export-stage-select');
  const previous = select.value;
  select.replaceChildren();
  if (!state.exportStages.length) {
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = 'No prepared stages';
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
  if (state.exportStages.some((stage) => stage.stage === previous)) select.value = previous;
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
  document.querySelector('#export-output').textContent = JSON.stringify(payload.manifest || payload, null, 2);
  await Promise.all([loadExportStages(), loadRepositoryStatus()]);
}

async function applySelectedExport() {
  const stage = document.querySelector('#export-stage-select').value;
  if (!stage) throw new Error('Prepare an export before applying one.');
  const payload = await requestJson('/api/export/apply', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({stage}),
  });
  const desktopNote = payload.opened_in_github_desktop
    ? 'GitHub Desktop opened automatically for the game checkout.'
    : 'Could not open GitHub Desktop automatically' + (payload.github_desktop_error ? (': ' + payload.github_desktop_error) : '.') + ' Open it manually to review, commit, and open a pull request.';
  document.querySelector('#export-output').textContent = 'Applied ' + payload.artifact + '.\nReview the game diff, then commit it locally.\n' + desktopNote;
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

function attachHomeEvents() {
  document.querySelector('#refresh-repository-status').addEventListener('click', () => loadRepositoryStatus().catch((error) => setText('#repository-message', error.message)));
  document.querySelector('#create-branch-button').addEventListener('click', () => createRepositoryBranch().catch((error) => setText('#repository-message', error.message)));
  document.querySelector('#commit-repository-button').addEventListener('click', () => commitRepositoryChanges().catch((error) => setText('#repository-message', error.message)));
  document.querySelector('#open-github-desktop-button').addEventListener('click', () => openRepositoryInDesktop().catch((error) => setText('#repository-message', error.message)));
  document.querySelector('#prepare-export-button').addEventListener('click', () => {
    document.querySelector('#export-output').textContent = 'Preparing export…';
    prepareExport().catch((error) => { document.querySelector('#export-output').textContent = error.message; });
  });
  document.querySelector('#apply-export-button').addEventListener('click', () => {
    document.querySelector('#export-output').textContent = 'Applying export…';
    applySelectedExport().catch((error) => { document.querySelector('#export-output').textContent = error.message; });
  });
}

async function loadHomeData() {
  const tools = await requestJson('/api/tools');
  renderTools(tools.tools || []);
  await Promise.all([loadRepositoryStatus(), loadExportStages()]);
}

function initializeHome() {
  attachHomeEvents();
  loadHomeData().catch((error) => setText('#repository-message', error.message));
}

initializeHome();
