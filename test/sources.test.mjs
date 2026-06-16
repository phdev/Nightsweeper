import { test } from 'node:test';
import assert from 'node:assert';
import { parseNotesLines, appleNotesSource, todoScanSource, githubSource } from '../lib/sources.mjs';

const NOTE = '<div><h1>AI learning path</h1></div><div><h2>Reading</h2></div>'
  + '<div>Read paper A</div><div><h2>Depthfinder</h2></div>'
  + '<div>Add coherence dimension [validator=test value=high]</div>'
  + '<div><s>old done thing</s></div><div>Wire warn-below gate</div>'
  + '<div><h2>Other</h2></div><div>Not this one</div>';

test('parseNotesLines detects headings + done', () => {
  const lines = parseNotesLines(NOTE);
  assert.ok(lines.find((l) => l.text === 'AI learning path' && l.isHeading));
  assert.ok(lines.find((l) => l.text === 'old done thing' && l.done));
});

test('apple_notes scopes to a heading, skips done, honors inline tags', () => {
  const s = appleNotesSource({ note: 'AI learning path', heading: 'Depthfinder' });
  s._fetchBody = () => NOTE;
  const tasks = s.fetch();
  assert.deepEqual(tasks.map((t) => t.title), ['Add coherence dimension', 'Wire warn-below gate']);
  assert.equal(tasks[0].validator, 'test');
  assert.equal(tasks[0].value, 'high');
  assert.equal(tasks[0].source, 'apple_notes');
});

test('apple_notes never invents work (empty note)', () => {
  const s = appleNotesSource({ note: 'x', heading: 'Nope' });
  s._fetchBody = () => '<div><h1>x</h1></div>';
  assert.equal(s.fetch().length, 0);
});

test('todo_scan only enrolls deliberate markers; bare TODOs ignored; tags parsed', () => {
  const FILE = [
    'function a() {',
    '  // TODO: bare one, not enrolled — must be left alone',
    '  // TODO(nightsweeper: validator=test value=high) wire the retry path',
    '  // TODO(nightsweeper: validator=build value=low)',
    '}',
  ].join('\n');
  const s = todoScanSource({ root: '/repo' });
  s._files = () => ['/repo/src/a.js'];
  s._read = () => FILE;
  const tasks = s.fetch();
  assert.equal(tasks.length, 2);
  const wired = tasks.find((t) => t.title === 'wire the retry path');
  assert.equal(wired.validator, 'test');
  assert.equal(wired.value, 'high');
  assert.equal(wired.source, 'todo_scan');
  // a marker with no trailing text falls back to a located description, keeps its tags
  const fallback = tasks.find((t) => t.title.startsWith('Resolve enrolled TODO'));
  assert.ok(fallback);
  assert.match(fallback.title, /src\/a\.js:4/);
  assert.equal(fallback.validator, 'build');
  assert.equal(fallback.value, 'low');
});

test('todo_scan returns nothing when no enrolled markers exist', () => {
  const s = todoScanSource({ root: '/repo' });
  s._files = () => ['/repo/x.js'];
  s._read = () => '// TODO: just a normal todo\n// FIXME: and a fixme\n';
  assert.equal(s.fetch().length, 0);
});

test('github_issues maps value labels + validator-prefixed labels, coerces bad ones', () => {
  const s = githubSource({
    repos: ['acme/widgets'],
    value_label_map: { 'priority:high': 'high', 'priority:low': 'low' },
    default_value: 'med', default_validator: 'test', validator_label_prefix: 'validator:',
  });
  s._list = () => [
    { number: 1, title: 'urgent bug', body: 'fix it', labels: [{ name: 'priority:high' }, { name: 'validator:build' }] },
    { number: 2, title: 'plain', body: 'x', labels: [] },
    { number: 3, title: 'bad labels', body: 'y', labels: [{ name: 'validator:bogus' }] },
  ];
  const tasks = s.fetch();
  assert.deepEqual(tasks.map((t) => t.id), ['gh:acme/widgets#1', 'gh:acme/widgets#2', 'gh:acme/widgets#3']);
  assert.equal(tasks[0].value, 'high');
  assert.equal(tasks[0].validator, 'build');
  assert.equal(tasks[1].value, 'med');          // default
  assert.equal(tasks[1].validator, 'test');     // default
  assert.equal(tasks[2].validator, 'test');     // 'bogus' coerced back to default
  assert.equal(tasks[0].source, 'github_issues');
});
