(() => {
  'use strict';

  async function requestJson(path, options = {}) {
    const response = await fetch(path, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : {};
    if (!response.ok) throw new Error(payload.error || ('Request failed (' + response.status + ')'));
    return payload;
  }

  function setStatus(text) {
    document.getElementById('debug-status').textContent = text;
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }

  function renderResults(container, items, emptyMessage, renderItem) {
    if (!items.length) {
      container.innerHTML = '<p class="metadata">' + escapeHtml(emptyMessage) + '</p>';
      return;
    }
    container.innerHTML = items.map(renderItem).join('');
  }

  async function runCoreFileLookup() {
    const container = document.getElementById('debug-results');
    const coreFile = document.getElementById('debug-core-file').value.trim();
    if (!coreFile) {
      renderResults(container, [], 'Enter a core file path first.', () => '');
      return;
    }
    const payload = await requestJson('/api/graph/edits?core_file=' + encodeURIComponent(coreFile));
    if (!payload.scanned) {
      renderResults(container, [], 'No content graph has been scanned yet.', () => '');
      return;
    }
    renderResults(container, payload.edits, 'No edits found for that core file.', (edit) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(edit.owner) + ' ' + escapeHtml(edit.edit_type) +
      (edit.line_number ? (' @ line ' + edit.line_number) : '') +
      ' (' + (edit.resolved ? 'resolved' : 'unresolved') + ')</div>' +
      '<div class="metadata">' + escapeHtml(edit.raw_label || edit.source_module_id || '(no label)') + '</div>' +
      '</div>'
    ));
  }

  async function runMissingReadmeLookup() {
    const container = document.getElementById('missing-readme-results');
    const payload = await requestJson('/api/graph/modules?missing_readme=true');
    if (!payload.scanned) {
      renderResults(container, [], 'No content graph has been scanned yet.', () => '');
      return;
    }
    renderResults(container, payload.modules, 'Every module has a readme.md.', (module) => (
      '<div class="unresolved-item">' +
      '<div class="path">' + escapeHtml(module.owner) + ':' + escapeHtml(module.module_id) + '</div>' +
      '<div class="metadata">' + escapeHtml(module.path) + '</div>' +
      '</div>'
    ));
  }

  function renderUnresolvedMarkerItem(marker) {
    const item = document.createElement('div');
    item.className = 'unresolved-item';

    const pathDiv = document.createElement('div');
    pathDiv.className = 'path';
    pathDiv.textContent = marker.core_file + ':' + marker.line_number;

    const metaDiv = document.createElement('div');
    metaDiv.textContent = marker.owner + ' ' + marker.edit_type + ' (' + marker.attribution + ')';

    const labelDiv = document.createElement('div');
    labelDiv.className = 'metadata';
    labelDiv.textContent = marker.raw_label || '(no label)';

    const actionsRow = document.createElement('div');
    actionsRow.className = 'button-row';
    const historyButton = document.createElement('button');
    historyButton.type = 'button';
    historyButton.className = 'secondary-button';
    historyButton.textContent = 'View history';
    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'secondary-button';
    editButton.textContent = 'Edit label';
    actionsRow.append(historyButton, editButton);

    const historyContainer = document.createElement('div');
    historyContainer.className = 'marker-history';
    historyContainer.hidden = true;

    const editContainer = document.createElement('div');
    editContainer.className = 'marker-edit';
    editContainer.hidden = true;

    item.append(pathDiv, metaDiv, labelDiv, actionsRow, historyContainer, editContainer);

    let historyLoaded = false;
    historyButton.addEventListener('click', async () => {
      historyContainer.hidden = !historyContainer.hidden;
      if (historyContainer.hidden || historyLoaded) return;
      historyLoaded = true;
      historyContainer.innerHTML = '<p class="metadata">Loading history…</p>';
      try {
        const payload = await requestJson('/api/graph/marker-history?core_file=' + encodeURIComponent(marker.core_file) + '&line=' + marker.line_number);
        if (!payload.commits.length) {
          historyContainer.innerHTML = '<p class="metadata">No Git history found for this line.</p>';
          return;
        }
        historyContainer.innerHTML = payload.commits.map((commit) => (
          '<div class="marker-history-commit">' +
          '<div><strong>' + escapeHtml(commit.short_commit) + '</strong> ' + escapeHtml(commit.author) + ' · ' + escapeHtml(commit.date) +
          (commit.pr_url ? ' · <a href="' + escapeHtml(commit.pr_url) + '" target="_blank" rel="noopener">Pull request</a>' : '') + '</div>' +
          '<div class="metadata">' + escapeHtml(commit.subject) + '</div>' +
          '<pre class="tool-output">' + escapeHtml(commit.diff) + '</pre>' +
          '</div>'
        )).join('');
      } catch (error) {
        historyContainer.innerHTML = '<p class="metadata">' + escapeHtml(error.message) + '</p>';
        historyLoaded = false;
      }
    });

    let editBuilt = false;
    editButton.addEventListener('click', () => {
      editContainer.hidden = !editContainer.hidden;
      if (editContainer.hidden || editBuilt) return;
      editBuilt = true;
      const input = document.createElement('input');
      input.type = 'text';
      input.value = marker.raw_label || '';
      const saveButton = document.createElement('button');
      saveButton.type = 'button';
      saveButton.textContent = 'Save';
      const statusText = document.createElement('p');
      statusText.className = 'metadata';
      const row = document.createElement('div');
      row.className = 'button-row';
      row.append(input, saveButton);
      editContainer.append(row, statusText);
      saveButton.addEventListener('click', () => {
        saveButton.disabled = true;
        requestJson('/api/graph/markers/edit', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            core_file: marker.core_file,
            line_number: marker.line_number,
            expected_line: marker.line_text,
            new_label: input.value,
          }),
        }).then(() => {
          statusText.textContent = '';
          const savedText = document.createElement('span');
          savedText.textContent = 'Saved. ';
          const rescanButton = document.createElement('button');
          rescanButton.type = 'button';
          rescanButton.className = 'secondary-button';
          rescanButton.textContent = 'Rescan to update the graph';
          rescanButton.addEventListener('click', () => runScan().catch((error) => setStatus(error.message)));
          statusText.append(savedText, rescanButton);
        }).catch((error) => {
          statusText.textContent = error.message;
        }).finally(() => {
          saveButton.disabled = false;
        });
      });
    });

    return item;
  }

  const MAX_UNRESOLVED_RENDERED = 200;

  async function runUnresolvedLookup() {
    const list = document.getElementById('unresolved-list');
    const payload = await requestJson('/api/graph/unresolved');
    list.replaceChildren();
    if (!payload.scanned) {
      const empty = document.createElement('p');
      empty.className = 'metadata';
      empty.textContent = 'No content graph has been scanned yet.';
      list.append(empty);
      return;
    }
    const markers = (payload.unresolved_markers || []).slice(0, MAX_UNRESOLVED_RENDERED);
    if (!markers.length) {
      const empty = document.createElement('p');
      empty.className = 'metadata';
      empty.textContent = 'No unresolved markers.';
      list.append(empty);
      return;
    }
    for (const marker of markers) {
      list.append(renderUnresolvedMarkerItem(marker));
    }
    const total = (payload.unresolved_markers || []).length;
    if (total > MAX_UNRESOLVED_RENDERED) {
      const more = document.createElement('p');
      more.className = 'metadata';
      more.textContent = (total - MAX_UNRESOLVED_RENDERED) + ' more not shown.';
      list.append(more);
    }
  }

  async function runScan() {
    setStatus('Rescanning…');
    const payload = await requestJson('/api/tools/scan-content', {method: 'POST'});
    await pollScan(payload.run_id);
  }

  async function pollScan(runId) {
    const payload = await requestJson('/api/tools/runs/' + encodeURIComponent(runId));
    if (payload.status === 'queued' || payload.status === 'running') {
      window.setTimeout(() => pollScan(runId).catch((error) => setStatus(error.message)), 750);
      return;
    }
    if (payload.status === 'succeeded') {
      setStatus('Rescan complete.');
      await Promise.all([runMissingReadmeLookup(), runUnresolvedLookup()]);
    } else {
      setStatus('Scan did not complete successfully.');
    }
  }

  async function init() {
    document.getElementById('debug-core-file-button').addEventListener('click', () => runCoreFileLookup().catch((error) => setStatus(error.message)));
    document.getElementById('debug-core-file').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runCoreFileLookup().catch((error) => setStatus(error.message));
    });
    document.getElementById('debug-missing-readme-button').addEventListener('click', () => runMissingReadmeLookup().catch((error) => setStatus(error.message)));

    try {
      const status = await requestJson('/api/graph/status');
      if (!status.scanned) {
        setStatus('No content graph has been scanned yet. Scan it from the Content Graph page first.');
        return;
      }
      setStatus('Scanned ' + status.manifest.generated_at + ' at revision ' + status.manifest.game_repo_revision.slice(0, 12) + '.');
      await Promise.all([runMissingReadmeLookup(), runUnresolvedLookup()]);
    } catch (error) {
      setStatus(error.message);
    }
  }

  if (typeof document !== 'undefined') {
    init();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {renderUnresolvedMarkerItem};
  }
})();
