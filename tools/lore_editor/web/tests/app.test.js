'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const app = require(path.join(__dirname, '..', 'app.js'));

test('statusLabel maps known statuses to their display labels and falls back for unknown ones', () => {
  assert.equal(app.statusLabel('needs-attention'), 'Needs attention');
  assert.equal(app.statusLabel('reviewed'), 'Reviewed');
  assert.equal(app.statusLabel('something-else'), 'something-else');
  assert.equal(app.statusLabel(undefined), 'Unknown');
});

test('groupMatchSummary joins group labels, preferring match reasons when present', () => {
  const entry = {
    groups: ['sol-federation', 'nanotrasen'],
    group_labels: ['Sol Federation', 'Nanotrasen'],
    group_match_reasons: {'sol-federation': ['keyword: solfed']},
  };

  assert.equal(app.groupMatchSummary(entry), 'Sol Federation — keyword: solfed · Nanotrasen');
});

test('groupMatchSummary returns an empty string when the entry has no groups', () => {
  assert.equal(app.groupMatchSummary({}), '');
});

test('slugify lowercases, hyphenates, and trims to 48 characters', () => {
  assert.equal(app.slugify('Sol Federation!'), 'sol-federation');
  assert.equal(app.slugify('  --Leading and Trailing--  '), 'leading-and-trailing');
  assert.equal(app.slugify(''), '');
  const long = 'a'.repeat(80);
  assert.equal(app.slugify(long).length, 48);
});

test('iconRecord reads from icon_metadata for the base icon and raw.icons for the override', () => {
  const entry = {
    icon_metadata: {icon: {file: 'base.dmi', state: 'icon'}},
    raw: {icons: {icon: {file: 'override.dmi', state: 'icon'}}},
  };

  assert.deepEqual(app.iconRecord(entry, 'icon', false), {file: 'base.dmi', state: 'icon'});
  assert.deepEqual(app.iconRecord(entry, 'icon', true), {file: 'override.dmi', state: 'icon'});
  assert.equal(app.iconRecord(entry, 'worn_icon', false), null);
});

test('isIconStateAvailable requires a cached, non-empty state list containing the requested state', () => {
  app.state.iconStates = new Map([['icons/obj/device.dmi', ['icon', 'icon-open']]]);

  assert.equal(app.isIconStateAvailable({file: 'icons/obj/device.dmi', state: 'icon'}), true);
  assert.equal(app.isIconStateAvailable({file: 'icons/obj/device.dmi', state: 'missing'}), false);
  assert.equal(app.isIconStateAvailable({file: 'icons/unknown.dmi', state: 'icon'}), false);
  assert.equal(app.isIconStateAvailable(null), false);
});

test('isIconStateAvailable treats an empty cached state list as "anything goes"', () => {
  app.state.iconStates = new Map([['icons/obj/device.dmi', []]]);

  assert.equal(app.isIconStateAvailable({file: 'icons/obj/device.dmi', state: 'whatever'}), true);
});

test('reviewQueryUrl encodes the active filters as query parameters', () => {
  app.state.filters.query = 'radio';
  app.state.filters.groups = new Set(['nanotrasen']);
  app.state.filters.statuses = new Set(['reviewed']);
  app.state.filters.sort = 'name';
  app.state.filters.includeDirectional = true;
  app.state.filters.includeRedundant = false;

  const url = app.reviewQueryUrl(50);
  const [path_, query] = url.split('?');
  const params = new URLSearchParams(query);

  assert.equal(path_, '/api/review');
  assert.equal(params.get('q'), 'radio');
  assert.equal(params.get('group'), 'nanotrasen');
  assert.equal(params.get('status'), 'reviewed');
  assert.equal(params.get('sort'), 'name');
  assert.equal(params.get('include_directional'), 'true');
  assert.equal(params.has('include_redundant'), false);
  assert.equal(params.get('offset'), '50');
});
