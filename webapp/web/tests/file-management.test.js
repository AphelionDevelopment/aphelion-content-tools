'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const app = require(path.join(__dirname, '..', 'file-management.js'));

test('repositoryLabel maps the game repository to its display name', () => {
  assert.equal(app.repositoryLabel('game'), 'Meridian-Rift');
});

test('repositoryLabel maps anything else (including "tool") to the tool repository label', () => {
  assert.equal(app.repositoryLabel('tool'), 'Aphelion Content Tools');
  assert.equal(app.repositoryLabel('unknown'), 'Aphelion Content Tools');
});
