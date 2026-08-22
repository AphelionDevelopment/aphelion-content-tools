(() => {
  'use strict';

const STATUS_LABELS = {
  unreviewed: 'Unreviewed',
  reviewed: 'Reviewed',
  overridden: 'Overridden',
  'needs-attention': 'Needs attention',
};
const REVIEW_API_PATH = '/api/review';
const REVIEW_PAGE_SIZE = 500;
const DEFAULT_KEYWORD_SCOPE = ['name', 'description', 'label'];

const state = {
  entries: [],
  selected: null,
  iconFiles: [],
  iconStates: new Map(),
  entityFiles: [],
  groups: [],
  filters: {
    query: '',
    groups: new Set(),
    statuses: new Set(Object.keys(STATUS_LABELS)),
    sort: 'name',
    includeDirectional: false,
    includeRedundant: false,
  },
  editing: false,
  iconDraftChanged: false,
  iconStateRequestSerial: 0,
  requestSerial: 0,
  reviewAbortController: null,
  matchedEntryCount: 0,
  hasMoreEntries: false,
  searchTimer: null,
  activeTab: 'review',
  groupDraftId: null,
  standalone: false,
  openActionsRequestSerial: 0,
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : {};
  if (!response.ok) throw new Error(payload.error || ('Request failed (' + response.status + ')'));
  return payload;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || 'Unknown';
}

function groupMatchSummary(entry) {
  return (entry.groups || [])
    .map((groupId, index) => {
      const label = entry.group_labels?.[index] || groupId;
      const reasons = entry.group_match_reasons?.[groupId] || [];
      return reasons.length ? label + ' — ' + reasons.join('; ') : label;
    })
    .join(' · ');
}

function slugify(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

function commaSeparatedValues(selector) {
  return document.querySelector(selector).value
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function setKeywordScopeCheckboxes(scope) {
  const active = new Set(scope);
  document.querySelectorAll('[data-scope-field]').forEach((input) => {
    input.checked = active.has(input.dataset.scopeField);
  });
}

function readKeywordScopeCheckboxes() {
  return Array.from(document.querySelectorAll('[data-scope-field]:checked')).map((input) => input.dataset.scopeField);
}

function keywordScopeSummary(scope) {
  return (scope && scope.length) ? scope.join(', ') : 'none (keywords never match)';
}

function renderGroups() {
  const container = document.querySelector('#group-filters');
  container.replaceChildren();
  if (!state.groups.length) {
    container.textContent = 'No groups configured.';
    return;
  }
  for (const group of state.groups) {
    const label = document.createElement('label');
    label.className = 'filter-option';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = group.id;
    input.checked = state.filters.groups.has(group.id);
    input.addEventListener('change', () => {
      if (input.checked) state.filters.groups.add(group.id);
      else state.filters.groups.delete(group.id);
      loadReviewEntries().catch((error) => setText('#status-message', error.message));
    });
    const swatch = document.createElement('span');
    swatch.className = 'group-swatch';
    swatch.style.backgroundColor = group.color;
    const text = document.createElement('span');
    text.textContent = group.label + ' (' + (group.count || 0) + ')';
    label.append(input, swatch, text);
    container.append(label);
  }
}

function renderConfigGroups() {
  const list = document.querySelector('#config-group-list');
  list.replaceChildren();
  if (!state.groups.length) {
    list.textContent = 'No groups configured.';
    return;
  }
  for (const group of state.groups) {
    const card = document.createElement('article');
    card.className = 'config-group-card';
    const heading = document.createElement('div');
    heading.className = 'config-group-heading';
    const swatch = document.createElement('span');
    swatch.className = 'group-swatch large';
    swatch.style.backgroundColor = group.color;
    const title = document.createElement('div');
    const label = document.createElement('strong');
    label.textContent = group.label;
    const id = document.createElement('span');
    id.className = 'metadata';
    id.textContent = group.id + ' · ' + (group.count || 0) + ' matches';
    title.append(label, id);
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'secondary-button text-button';
    edit.textContent = 'Edit';
    edit.addEventListener('click', () => editGroup(group.id));
    heading.append(swatch, title, edit);
    const keywords = document.createElement('p');
    keywords.className = 'metadata';
    keywords.textContent = (group.keywords || []).length ? 'Keywords: ' + group.keywords.join(', ') : 'Keywords: none';
    const prefixes = document.createElement('p');
    prefixes.className = 'metadata';
    prefixes.textContent = (group.type_path_prefixes || []).length ? 'Type paths: ' + group.type_path_prefixes.join(', ') : 'Type paths: none';
    const scope = document.createElement('p');
    scope.className = 'metadata';
    scope.textContent = 'Keyword scope: ' + keywordScopeSummary(group.keyword_scope);
    card.append(heading, keywords, prefixes, scope);
    list.append(card);
  }
}

function renderEntityFiles() {
  const select = document.querySelector('#override-source');
  select.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Choose an existing entity group';
  select.append(placeholder);
  for (const file of state.entityFiles) {
    const option = document.createElement('option');
    option.value = file;
    option.textContent = file.split('/').pop();
    select.append(option);
  }
}

function renderIconFileOptions() {
  const datalist = document.querySelector('#icon-file-options');
  datalist.replaceChildren();
  for (const file of state.iconFiles) {
    const option = document.createElement('option');
    option.value = file;
    datalist.append(option);
  }
}

function renderEntries() {
  const list = document.querySelector('#entry-list');
  list.replaceChildren();
  document.querySelector('#result-count').textContent = state.matchedEntryCount > state.entries.length
    ? state.entries.length + ' / ' + state.matchedEntryCount
    : String(state.entries.length);
  if (!state.entries.length) {
    list.textContent = 'No catalog targets match these filters.';
    return;
  }
  for (const entry of state.entries) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'entry-button status-' + (entry.status || 'unreviewed');
    button.setAttribute('aria-label', (entry.name || entry.base_name || entry.label || entry.type_path || 'Unnamed entry') + ', ' + statusLabel(entry.status));
    const heading = document.createElement('strong');
    heading.textContent = entry.name || entry.base_name || entry.label || entry.type_path || 'Unnamed entry';
    const metadata = document.createElement('span');
    metadata.className = 'entry-button-metadata';
    metadata.textContent = (entry.type_path || '<unknown>') + ' · ' + statusLabel(entry.status);
    const groups = document.createElement('span');
    groups.className = 'entry-button-groups';
    groups.textContent = (entry.group_labels || []).join(' · ');
    const groupSummary = groupMatchSummary(entry);
    if (groupSummary) groups.title = groupSummary;
    button.append(heading, metadata, groups);
    if (entry.suppression_reasons?.length) {
      const suppression = document.createElement('span');
      suppression.className = 'entry-button-suppression';
      suppression.textContent = 'Visible by toggle: ' + entry.suppression_reasons.join(', ');
      button.append(suppression);
    }
    button.addEventListener('click', () => selectEntry(entry));
    list.append(button);
  }
  if (state.hasMoreEntries) {
    const loadMore = document.createElement('button');
    loadMore.type = 'button';
    loadMore.className = 'secondary-button load-more-button';
    loadMore.textContent = 'Load more entries';
    loadMore.disabled = state.loadingMoreEntries === true;
    loadMore.addEventListener('click', () => loadReviewEntries({append: true}).catch((error) => setText('#status-message', error.message)));
    list.append(loadMore);
  }
}

function iconRecord(entry, field, override) {
  const source = override ? entry.raw?.icons?.[field] : entry.icon_metadata?.[field];
  return source && typeof source === 'object' ? source : null;
}

function isIconStateAvailable(record) {
  if (!record?.file || !record?.state || !state.iconStates.has(record.file)) return false;
  const states = state.iconStates.get(record.file) || [];
  return !states.length || states.includes(record.state);
}

function setImagePreview(selector, record, failureMessage) {
  const preview = document.querySelector(selector);
  if (!isIconStateAvailable(record)) {
    preview.removeAttribute('src');
    preview.hidden = true;
    return;
  }
  preview.src = '/api/icon?file=' + encodeURIComponent(record.file) + '&state=' + encodeURIComponent(record.state);
  preview.hidden = false;
  preview.onerror = () => {
    preview.hidden = true;
    setText('#icon-message', failureMessage);
  };
}

function renderIconStateOptions(states, selectedState) {
  const select = document.querySelector('#icon-state');
  select.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Choose an icon state';
  select.append(placeholder);
  for (const iconState of states || []) {
    const option = document.createElement('option');
    option.value = iconState;
    option.textContent = iconState;
    select.append(option);
  }
  if (selectedState && !(states || []).includes(selectedState)) {
    const unavailable = document.createElement('option');
    unavailable.value = selectedState;
    unavailable.textContent = selectedState + ' (unavailable)';
    unavailable.disabled = true;
    select.append(unavailable);
  }
  select.value = (states || []).includes(selectedState) ? selectedState : '';
  select.disabled = !document.querySelector('#icon-file-input').value;
}

async function loadIconStates(file, selectedState = '') {
  if (!file) {
    renderIconStateOptions([], '');
    updateIconPreviews();
    return;
  }
  const requestSerial = ++state.iconStateRequestSerial;
  const cached = state.iconStates.get(file);
  if (cached) {
    renderIconStateOptions(cached, selectedState);
    updateIconPreviews();
  }
  try {
    const payload = await requestJson('/api/icon-states?file=' + encodeURIComponent(file));
    if (requestSerial !== state.iconStateRequestSerial) return;
    const states = payload.states || [];
    state.iconStates.set(file, states);
    renderIconStateOptions(states, selectedState);
    updateIconPreviews();
  } catch (error) {
    if (requestSerial === state.iconStateRequestSerial) {
      renderIconStateOptions([], selectedState);
      setText('#icon-message', error.message);
    }
  }
}

function renderIconEditor(entry) {
  const field = document.querySelector('#icon-field').value;
  const baseRecord = iconRecord(entry, field, false);
  const overrideRecord = iconRecord(entry, field, true);
  const selectedRecord = overrideRecord || baseRecord;
  const baseReference = document.querySelector('#base-icon-reference');
  baseReference.textContent = baseRecord?.file && baseRecord?.state
    ? baseRecord.file + ' · ' + baseRecord.state
    : 'No base icon reference.';
  const fileInput = document.querySelector('#icon-file-input');
  fileInput.value = selectedRecord?.file || '';
  const availableStates = selectedRecord?.available_states || state.iconStates.get(fileInput.value) || [];
  if (fileInput.value && availableStates.length) state.iconStates.set(fileInput.value, availableStates);
  renderIconStateOptions(availableStates, selectedRecord?.state || '');
  updateIconPreviews();
  setText('#icon-message', state.iconFiles.length ? 'Choose a repository DMI file and state for an override.' : 'No DMI assets were found.');
  if (fileInput.value) loadIconStates(fileInput.value, selectedRecord?.state || '');
}

function updateIconPreviews() {
  if (!state.selected) return;
  const field = document.querySelector('#icon-field').value;
  const baseRecord = iconRecord(state.selected, field, false);
  setImagePreview('#icon-base-preview', baseRecord, 'The base icon could not be previewed.');
  const overrideRecord = iconRecord(state.selected, field, true);
  const file = document.querySelector('#icon-file-input').value;
  const iconState = document.querySelector('#icon-state').value;
  const shouldPreviewOverride = Boolean(overrideRecord || (state.editing && state.iconDraftChanged));
  if (shouldPreviewOverride && file && iconState) {
    setImagePreview('#icon-override-preview', {file, state: iconState}, 'That override icon could not be previewed.');
  } else {
    const preview = document.querySelector('#icon-override-preview');
    preview.removeAttribute('src');
    preview.hidden = true;
  }
}

function setWikiControls() {
  const enabled = document.querySelector('#wiki-enabled').checked && state.editing;
  document.querySelector('#wiki-slug').disabled = !enabled;
  document.querySelector('#wiki-summary').disabled = !enabled;
  document.querySelector('#wiki-export-icon').disabled = !enabled;
}

function setEditorControls() {
  const canEdit = state.editing;
  const hasSpecialDescriptionEditor = state.selected?.field_profile === 'atom_like';
  for (const selector of ['#entry-name', '#entry-description', '#entry-special-desc-requirement', '#entry-special-desc', '#wiki-enabled']) {
    document.querySelector(selector).disabled = !canEdit;
  }
  document.querySelector('#special-desc-editor').hidden = !hasSpecialDescriptionEditor;
  document.querySelector('#entry-special-desc-requirement').disabled = !canEdit || !hasSpecialDescriptionEditor;
  document.querySelector('#entry-special-desc').disabled = !canEdit || !hasSpecialDescriptionEditor;
  const hasIconEditor = state.selected && state.selected.field_profile !== 'named_datum';
  document.querySelector('#icon-field').disabled = !hasIconEditor;
  document.querySelector('#icon-file-input').disabled = !hasIconEditor;
  document.querySelector('#icon-state').disabled = !hasIconEditor || !document.querySelector('#icon-file-input').value;
  setWikiControls();
  document.querySelector('#save-button').hidden = !canEdit;
  document.querySelector('#override-source-editor').hidden = !state.selected || state.selected.has_override;
  document.querySelector('#create-override-button').hidden = !state.selected || state.selected.has_override || state.editing;
  document.querySelector('#remove-override-button').hidden = !state.selected || !state.selected.has_override;
}

// The "Open in..." menu itself (floating positioning, the three actions) is a shared component -- see
// webapp/web/open-in-menu.js -- used here and by Content Graph, instead of two separately-broken
// reimplementations (this file's old always-visible three-button row; Content Graph's old dropdown that
// forced its scrolling panel to grow).
function renderOpenActionsRow(label, repository, path, line) {
  const row = document.createElement('div');
  row.className = 'open-actions-row';
  const heading = document.createElement('span');
  heading.className = 'metadata';
  heading.textContent = label + (line ? ' (line ' + line + ')' : '') + ':';
  row.append(heading);
  window.AphelionOpenInMenu.render(row, {repository, path, line, onError: (message) => setText('#status-message', message)});
  return row;
}

async function renderEntryOpenActions(entry) {
  const container = document.querySelector('#entry-open-actions');
  container.replaceChildren();
  const requestSerial = ++state.openActionsRequestSerial;

  const originalRow = document.createElement('div');
  originalRow.className = 'open-actions-group';
  const originalLabel = document.createElement('p');
  originalLabel.className = 'metadata';
  originalLabel.textContent = 'Looking up the original DM source…';
  originalRow.append(originalLabel);
  container.append(originalRow);

  if (entry.has_override && entry.source_file) {
    const overrideGroup = document.createElement('div');
    overrideGroup.className = 'open-actions-group';
    overrideGroup.append(renderOpenActionsRow('Open override in', 'tool', entry.source_file));
    container.append(overrideGroup);
  }

  if (!entry.type_path) return;
  try {
    const definition = await requestJson('/api/lore/definition?type_path=' + encodeURIComponent(entry.type_path));
    if (requestSerial !== state.openActionsRequestSerial) return;
    if (definition.path) {
      originalRow.replaceChildren(renderOpenActionsRow('Open original in', 'game', definition.path, definition.line));
    } else {
      originalLabel.textContent = 'Could not find this type\'s definition in the game checkout.';
    }
  } catch (error) {
    if (requestSerial !== state.openActionsRequestSerial) return;
    originalLabel.textContent = error.message;
  }
}

function selectEntry(entry) {
  state.selected = entry;
  state.editing = Boolean(entry.has_override);
  state.iconDraftChanged = false;
  document.querySelector('#empty-editor').hidden = true;
  document.querySelector('#entry-form').hidden = false;
  document.querySelector('#review-controls').hidden = false;
  document.querySelector('#entry-mode').textContent = entry.has_override
    ? 'Approved override — this entry can be edited.'
    : 'Catalog target — review the base content or create an override.';
  document.querySelector('#entry-status').hidden = false;
  document.querySelector('#entry-status').textContent = statusLabel(entry.status);
  document.querySelector('#entry-status').className = 'status-pill status-' + (entry.status || 'unreviewed');
  document.querySelector('#review-notes').value = entry.review?.notes || '';
  document.querySelector('#entry-name').value = entry.name || entry.base_name || '';
  document.querySelector('#entry-description').value = entry.description || entry.base_description || '';
  document.querySelector('#entry-special-desc-requirement').value = entry.special_desc_requirement ?? entry.raw?.special_desc_requirement ?? '';
  document.querySelector('#entry-special-desc').value = entry.special_desc ?? entry.raw?.special_desc ?? '';
  const groupSummary = groupMatchSummary(entry);
  document.querySelector('#entry-metadata').textContent = (entry.id || '<unknown>') + ' · ' + (entry.type_path || '<unknown>') + ' · ' + (entry.field_profile || 'profile unavailable') + (groupSummary ? ' · ' + groupSummary : '') + (entry.suppression_reasons?.length ? ' · visible by toggle: ' + entry.suppression_reasons.join(', ') : '');
  document.querySelector('#before-preview').textContent = entry.base_name || '(no base name)';
  document.querySelector('#before-description-preview').textContent = entry.base_description || '(no base description)';
  document.querySelector('#after-preview').textContent = entry.name || entry.base_name || '(unchanged)';
  document.querySelector('#after-description-preview').textContent = entry.description || entry.base_description || '(unchanged)';
  const wiki = entry.raw?.wiki || {};
  document.querySelector('#wiki-enabled').checked = wiki.enabled === true;
  document.querySelector('#wiki-slug').value = wiki.slug || '';
  document.querySelector('#wiki-summary').value = wiki.summary || '';
  document.querySelector('#wiki-export-icon').checked = wiki.export_icon === true;
  document.querySelector('#icon-editor').hidden = entry.field_profile === 'named_datum';
  document.querySelector('#icon-field').value = 'icon';
  renderIconEditor(entry);
  setEditorControls();
  renderEntryOpenActions(entry);
  document.querySelector('#validation-panel').textContent = '';
}

function formEntry() {
  const entry = clone(state.selected.raw || {});
  entry.id = state.selected.draft_id || state.selected.id;
  entry.type_path = state.selected.type_path;
  const name = document.querySelector('#entry-name').value.trim();
  const description = document.querySelector('#entry-description').value.trim();
  const specialDescRequirement = document.querySelector('#entry-special-desc-requirement').value;
  const specialDesc = document.querySelector('#entry-special-desc').value.trim();
  if (name) entry.name = name; else delete entry.name;
  if (description) entry.description = description; else delete entry.description;
  if (specialDescRequirement) entry.special_desc_requirement = specialDescRequirement; else delete entry.special_desc_requirement;
  if (specialDesc) entry.special_desc = specialDesc; else delete entry.special_desc;

  const iconField = document.querySelector('#icon-field').value;
  const iconFile = document.querySelector('#icon-file-input').value.trim();
  const iconState = document.querySelector('#icon-state').value;
  if (iconFile && iconState && (state.iconDraftChanged || entry.icons?.[iconField])) {
    entry.icons = entry.icons || {};
    entry.icons[iconField] = {file: iconFile, state: iconState};
  }

  if (document.querySelector('#wiki-enabled').checked) {
    entry.wiki = {
      enabled: true,
      slug: document.querySelector('#wiki-slug').value.trim(),
      summary: document.querySelector('#wiki-summary').value.trim(),
      export_icon: document.querySelector('#wiki-export-icon').checked,
    };
  } else {
    delete entry.wiki;
  }
  return entry;
}

function displayIssues(issues) {
  document.querySelector('#validation-panel').textContent = (issues || [])
    .map((issue) => issue.path + ': ' + issue.message)
    .join('\n');
}

function refreshReviewTarget(typePath) {
  const refreshed = state.entries.find((entry) => entry.type_path === typePath);
  if (refreshed) selectEntry(refreshed);
}

function reviewQueryUrl(offset = 0) {
  const params = new URLSearchParams();
  if (state.filters.query) params.set('q', state.filters.query);
  for (const group of state.filters.groups) params.append('group', group);
  for (const status of state.filters.statuses) params.append('status', status);
  params.set('sort', state.filters.sort);
  if (state.filters.includeDirectional) params.set('include_directional', 'true');
  if (state.filters.includeRedundant) params.set('include_redundant', 'true');
  params.set('offset', String(offset));
  params.set('limit', String(REVIEW_PAGE_SIZE));
  return REVIEW_API_PATH + '?' + params.toString();
}

async function loadReviewEntries({append = false} = {}) {
  const requestSerial = ++state.requestSerial;
  state.reviewAbortController?.abort();
  const abortController = new AbortController();
  state.reviewAbortController = abortController;
  if (!state.filters.statuses.size) {
    state.entries = [];
    state.matchedEntryCount = 0;
    state.hasMoreEntries = false;
    renderEntries();
    setText('#status-message', 'No review statuses selected.');
    return {entries: []};
  }
  state.loadingMoreEntries = append;
  try {
    const payload = await requestJson(reviewQueryUrl(append ? state.entries.length : 0), {signal: abortController.signal});
    if (requestSerial !== state.requestSerial) return payload;
    state.entries = append ? state.entries.concat(payload.entries || []) : (payload.entries || []);
    state.matchedEntryCount = payload.matched_entry_count ?? state.entries.length;
    state.hasMoreEntries = payload.has_more === true;
    renderEntries();
    if (payload.group_counts) {
      state.groups = state.groups.map((group) => ({...group, count: payload.group_counts[group.id] || 0}));
      renderGroups();
      renderConfigGroups();
    }
    const total = payload.catalog_count || 0;
	  const visible = payload.visible_entry_count ?? payload.visible_catalog_count ?? total;
    const suppressed = payload.suppressed_counts || {};
    setText('#status-message', visible + ' visible of ' + total + ' catalog targets · ' + (payload.approved_count || 0) + ' overrides.');
    setText('#suppression-summary', (suppressed.directional || suppressed.redundant)
      ? (suppressed.directional || 0) + ' directional and ' + (suppressed.redundant || 0) + ' redundant targets hidden.'
      : 'No suppressed catalog targets.');
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') return {entries: []};
    throw error;
  } finally {
    if (requestSerial === state.requestSerial) {
      state.loadingMoreEntries = false;
      state.reviewAbortController = null;
    }
  }
}

async function loadGroupsData() {
  const payload = await requestJson('/api/groups');
  state.groups = payload.groups || [];
  renderGroups();
  renderConfigGroups();
  return payload;
}

function setActiveTab(tab) {
  state.activeTab = tab;
  const reviewActive = tab === 'review';
  document.querySelector('#review-panel').hidden = !reviewActive;
  document.querySelector('#configuration-panel').hidden = reviewActive;
  document.querySelector('#review-tab').classList.toggle('active', reviewActive);
  document.querySelector('#config-tab').classList.toggle('active', !reviewActive);
  document.querySelector('#review-tab').setAttribute('aria-selected', String(reviewActive));
  document.querySelector('#config-tab').setAttribute('aria-selected', String(!reviewActive));
}

function startNewGroup() {
  state.groupDraftId = null;
  setActiveTab('config');
  document.querySelector('#group-editor').hidden = false;
  document.querySelector('#group-editor-title').textContent = 'New group';
  document.querySelector('#new-group-id').disabled = false;
  for (const selector of ['#new-group-id', '#new-group-label', '#new-group-keywords', '#new-group-prefixes']) document.querySelector(selector).value = '';
  document.querySelector('#new-group-color').value = '#9614d0';
  setKeywordScopeCheckboxes(DEFAULT_KEYWORD_SCOPE);
  document.querySelector('#new-group-id').focus();
}

function editGroup(groupId) {
  const group = state.groups.find((candidate) => candidate.id === groupId);
  if (!group) return;
  state.groupDraftId = group.id;
  document.querySelector('#group-editor').hidden = false;
  document.querySelector('#group-editor-title').textContent = 'Edit ' + group.label;
  document.querySelector('#new-group-id').value = group.id;
  document.querySelector('#new-group-id').disabled = true;
  document.querySelector('#new-group-label').value = group.label;
  document.querySelector('#new-group-color').value = group.color;
  document.querySelector('#new-group-keywords').value = (group.keywords || []).join(', ');
  document.querySelector('#new-group-prefixes').value = (group.type_path_prefixes || []).join(', ');
  setKeywordScopeCheckboxes(group.keyword_scope || DEFAULT_KEYWORD_SCOPE);
  document.querySelector('#new-group-label').focus();
}

async function saveGroup(event) {
  event.preventDefault();
  const groupId = document.querySelector('#new-group-id').value.trim();
  const payload = {
    id: groupId,
    label: document.querySelector('#new-group-label').value.trim(),
    color: document.querySelector('#new-group-color').value.trim(),
    keywords: commaSeparatedValues('#new-group-keywords'),
    type_path_prefixes: commaSeparatedValues('#new-group-prefixes'),
    keyword_scope: readKeywordScopeCheckboxes(),
  };
  const saveButton = document.querySelector('#save-group-button');
  saveButton.disabled = true;
  try {
    const path = state.groupDraftId ? '/api/groups/' + encodeURIComponent(state.groupDraftId) : '/api/groups';
    const response = await requestJson(path, {
      method: state.groupDraftId ? 'PUT' : 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    document.querySelector('#group-editor').hidden = true;
    state.groupDraftId = null;
    // Re-render immediately from the server's echoed response (label/color/keywords/scope, but not yet
    // this group's match count -- that needs the full reclassification loadGroupsData() below performs)
    // so the swatch and text update the instant the save succeeds, rather than only after the slower
    // full-corpus reclassification finishes.
    const savedGroup = response.group || payload;
    const existingIndex = state.groups.findIndex((candidate) => candidate.id === savedGroup.id);
    if (existingIndex >= 0) state.groups[existingIndex] = {...state.groups[existingIndex], ...savedGroup};
    else state.groups.push(savedGroup);
    renderGroups();
    renderConfigGroups();
    setText('#status-message', 'Group configuration saved.');
    await loadGroupsData();
    await loadReviewEntries();
  } finally {
    saveButton.disabled = false;
  }
}

async function saveReview(status) {
  if (!state.selected) return;
  if ((status === 'reviewed' || status === 'needs-attention') && !document.querySelector('#reviewer-name').value.trim()) {
    throw new Error('Enter a reviewer name before saving a review decision.');
  }
  const payload = status
    ? {
      status,
      reviewed_by: document.querySelector('#reviewer-name').value.trim(),
      notes: document.querySelector('#review-notes').value.trim(),
    }
    : {status: null};
  await requestJson('/api/reviews/' + encodeURIComponent(state.selected.type_path), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const typePath = state.selected.type_path;
  await loadReviewEntries();
  refreshReviewTarget(typePath);
}

function createOverride() {
  if (!state.selected) return;
  const label = state.selected.name || state.selected.base_name || state.selected.label || state.selected.type_path.split('/').pop();
  const draftId = 'lore.' + slugify(state.selected.type_path || label);
  state.selected.draft_id = draftId;
  state.selected.raw = {id: draftId, type_path: state.selected.type_path};
  state.editing = true;
  state.iconDraftChanged = false;
  document.querySelector('#override-source-editor').hidden = false;
  document.querySelector('#entry-mode').textContent = 'Draft override — choose an entity group, edit the fields, then save.';
  renderIconEditor(state.selected);
  setEditorControls();
}

async function removeOverride() {
  if (!state.selected || !state.selected.has_override) return;
  const label = state.selected.name || state.selected.base_name || state.selected.type_path;
  if (!window.confirm('Remove the override for "' + label + '"? It will revert to its base catalog definition.')) return;
  const removeButton = document.querySelector('#remove-override-button');
  removeButton.disabled = true;
  try {
    await requestJson('/api/entries/' + encodeURIComponent(state.selected.id), {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_file: state.selected.source_file}),
    });
    setText('#status-message', 'Override removed and generated.');
    const typePath = state.selected.type_path;
    await loadReviewEntries();
    refreshReviewTarget(typePath);
  } catch (error) {
    setText('#status-message', error.message);
  } finally {
    removeButton.disabled = false;
  }
}

function selectedSourceFile() {
  if (state.selected.has_override) return state.selected.source_file;
  const newGroup = document.querySelector('#new-override-group').value.trim();
  if (newGroup) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(newGroup)) throw new Error('New override group must use lowercase letters, numbers, and hyphens.');
    return (state.standalone
      ? 'tools/lore_editor/content/overrides/'
      : 'config/aphelion/lore_overhaul/entities/') + newGroup + '.json';
  }
  const existing = document.querySelector('#override-source').value;
  if (!existing) throw new Error('Choose an existing entity group or enter a new group file name.');
  return existing;
}

async function validateFormEntry() {
  const entry = formEntry();
  const payload = await requestJson('/api/validate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({entries: [entry], source_file: state.selected.source_file || selectedSourceFile()}),
  });
  displayIssues(payload.issues);
  return {entry, payload};
}

async function saveEntry(event) {
  event.preventDefault();
  if (!state.selected || !state.editing) return;
  const saveButton = document.querySelector('#save-button');
  saveButton.disabled = true;
  try {
    const validation = state.selected.has_override
      ? await validateFormEntry()
      : {entry: formEntry(), payload: {valid: true, issues: []}};
    if (!validation.payload.valid) throw new Error('Save cancelled until validation issues are fixed.');
    if (state.selected.has_override) {
      const response = await requestJson('/api/entries/' + encodeURIComponent(state.selected.id), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_file: state.selected.source_file, entry: validation.entry}),
      });
      setText('#status-message', response.saved ? 'Saved and generated.' : 'Save completed.');
    } else {
      const response = await requestJson('/api/entries', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_file: selectedSourceFile(), entry: validation.entry}),
      });
      setText('#status-message', response.created ? 'Override created and generated.' : 'Override saved.');
    }
    const typePath = state.selected.type_path;
    await loadReviewEntries();
    refreshReviewTarget(typePath);
  } catch (error) {
    document.querySelector('#validation-panel').textContent = error.message;
  } finally {
    saveButton.disabled = false;
  }
}

function attachEditorEvents() {
  document.querySelector('#review-tab').addEventListener('click', () => setActiveTab('review'));
  document.querySelector('#config-tab').addEventListener('click', () => setActiveTab('config'));
  document.querySelector('#create-group-button').addEventListener('click', startNewGroup);
  document.querySelector('#config-new-group-button').addEventListener('click', startNewGroup);
  document.querySelector('#cancel-group-button').addEventListener('click', () => { document.querySelector('#group-editor').hidden = true; state.groupDraftId = null; });
  document.querySelector('#group-editor').addEventListener('submit', (event) => saveGroup(event).catch((error) => setText('#status-message', error.message)));
  document.querySelector('#select-all-group-filters').addEventListener('click', () => {
    state.filters.groups = new Set(state.groups.map((group) => group.id));
    renderGroups();
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#clear-group-filters').addEventListener('click', () => {
    state.filters.groups.clear();
    renderGroups();
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#clear-status-filters').addEventListener('click', () => {
    state.filters.statuses = new Set(Object.keys(STATUS_LABELS));
    document.querySelectorAll('#status-filters input[name="status"]').forEach((input) => { input.checked = true; });
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#show-directional').addEventListener('change', (event) => {
    state.filters.includeDirectional = event.target.checked;
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#show-redundant').addEventListener('change', (event) => {
    state.filters.includeRedundant = event.target.checked;
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelectorAll('#status-filters input[name="status"]').forEach((input) => {
    input.addEventListener('change', () => {
      state.filters.statuses = new Set(Array.from(document.querySelectorAll('#status-filters input[name="status"]:checked')).map((item) => item.value));
      loadReviewEntries().catch((error) => setText('#status-message', error.message));
    });
  });
  document.querySelector('#sort-select').addEventListener('change', (event) => {
    state.filters.sort = event.target.value;
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#clear-filters').addEventListener('click', () => {
    state.filters.query = '';
    state.filters.groups.clear();
    state.filters.statuses = new Set(Object.keys(STATUS_LABELS));
    state.filters.sort = 'name';
    state.filters.includeDirectional = false;
    state.filters.includeRedundant = false;
    document.querySelector('#search').value = '';
    document.querySelector('#sort-select').value = 'name';
    document.querySelector('#show-directional').checked = false;
    document.querySelector('#show-redundant').checked = false;
    document.querySelectorAll('#status-filters input[name="status"]').forEach((input) => { input.checked = true; });
    renderGroups();
    loadReviewEntries().catch((error) => setText('#status-message', error.message));
  });
  document.querySelector('#search').addEventListener('input', (event) => {
    state.filters.query = event.target.value.trim();
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(() => loadReviewEntries().catch((error) => setText('#status-message', error.message)), 150);
  });
  document.querySelector('#entry-name').addEventListener('input', (event) => setText('#after-preview', event.target.value || '(unchanged)'));
  document.querySelector('#entry-description').addEventListener('input', (event) => setText('#after-description-preview', event.target.value || '(unchanged)'));
  document.querySelector('#wiki-enabled').addEventListener('change', setWikiControls);
  document.querySelector('#icon-field').addEventListener('change', () => { state.iconDraftChanged = false; renderIconEditor(state.selected); setEditorControls(); });
  document.querySelector('#icon-file-input').addEventListener('input', (event) => {
    state.iconDraftChanged = true;
    loadIconStates(event.target.value.trim(), '').catch((error) => setText('#icon-message', error.message));
    updateIconPreviews();
    setEditorControls();
  });
  document.querySelector('#icon-state').addEventListener('change', () => { state.iconDraftChanged = true; updateIconPreviews(); });
  document.querySelector('#entry-form').addEventListener('submit', saveEntry);
  document.querySelector('#create-override-button').addEventListener('click', createOverride);
  document.querySelector('#remove-override-button').addEventListener('click', () => removeOverride().catch((error) => setText('#status-message', error.message)));
  document.querySelector('#mark-reviewed-button').addEventListener('click', () => saveReview('reviewed').catch((error) => setText('#status-message', error.message)));
  document.querySelector('#flag-attention-button').addEventListener('click', () => saveReview('needs-attention').catch((error) => setText('#status-message', error.message)));
  document.querySelector('#clear-review-button').addEventListener('click', () => saveReview(null).catch((error) => setText('#status-message', error.message)));
}

async function loadEditorData() {
  const [catalog, icons, groups, files] = await Promise.all([
    requestJson('/api/catalog'),
    requestJson('/api/icon-files'),
    requestJson('/api/groups'),
    requestJson('/api/entity-files'),
  ]);
  state.standalone = catalog.standalone === true;
  state.iconFiles = icons.files || [];
  state.groups = groups.groups || [];
  state.entityFiles = files.files || [];
  renderIconFileOptions();
  renderGroups();
  renderConfigGroups();
  renderEntityFiles();
  await loadReviewEntries();
}

function initializeEditor() {
  attachEditorEvents();
  loadEditorData().catch((error) => setText('#status-message', error.message));
}

function showServerLaunchMessage() {
  setText('#status-message', 'This editor must be launched through the repository server. Run: python webapp/serve.py --repo-root . --port 0');
  document.querySelector('#search').disabled = true;
}

async function selectEntryByTypePath(typePath, query) {
  document.querySelector('#search').value = query || '';
  state.filters.query = query || '';
  state.filters.groups.clear();
  state.filters.statuses = new Set(Object.keys(STATUS_LABELS));
  document.querySelectorAll('#status-filters input[name="status"]').forEach((input) => { input.checked = true; });
  renderGroups();
  const payload = await loadReviewEntries();
  const match = (payload.entries || []).find((entry) => entry.type_path === typePath);
  if (match) {
    setActiveTab('review');
    selectEntry(match);
  } else {
    setText('#status-message', 'Could not find that entry — it may be filtered out or no longer exist.');
  }
}

if (typeof window !== 'undefined') {
  if (window.location.protocol === 'file:') showServerLaunchMessage();
  else initializeEditor();

  window.addEventListener('aphelion:search-select-entry', (event) => {
    if (!event.detail || !event.detail.typePath) return;
    selectEntryByTypePath(event.detail.typePath, event.detail.query).catch((error) => setText('#status-message', error.message));
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {state, statusLabel, groupMatchSummary, slugify, iconRecord, isIconStateAvailable, reviewQueryUrl};
}

})();
