// Runs the built engine (site/planner.wasm) against every class in site/data.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const root = new URL('../site/', import.meta.url);
const json = (name) => JSON.parse(readFileSync(new URL(`data/${name}.json`, root), 'utf8'));
const { instance } = await WebAssembly.instantiate(readFileSync(new URL('planner.wasm', root)), {});
const W = instance.exports;
const manifest = json('manifest');

const io = () => new Uint8Array(W.memory.buffer, W.pl_io(), 1024);
const exportCode = () => String.fromCharCode(...io().subarray(0, W.pl_export()));
const importCode = (s) => { const m = io(); [...s].forEach((c, i) => { m[i] = c.charCodeAt(0); }); m[s.length] = 0; return W.pl_import(); };

function load(doc) {
  const r = manifest.rules;
  W.pl_reset();
  W.pl_set_rules(r.first_point_level, r.max_level, r.points_per_row);
  doc.trees.forEach((tree) => {
    const ti = W.pl_add_tree();
    const index = new Map(tree.talents.map((t, i) => [t.name, i]));
    tree.talents.forEach((t) => assert.ok(W.pl_add_talent(ti, t.row, t.col, t.max, -1) >= 0, t.name));
    tree.talents.forEach((t, i) => { if (t.req) assert.equal(W.pl_set_req(ti, i, index.get(t.req)), 0, t.name); });
  });
}

// Spend points top to bottom in one tree until nothing more can be added.
function fill(doc, ti) {
  let progress = true;
  while (progress) {
    progress = false;
    doc.trees[ti].talents.forEach((t, i) => { while (W.pl_add(ti, i) === 0) progress = true; });
  }
}

for (const c of manifest.classes) {
  const doc = json(c.key);
  assert.equal(doc.trees.length, 3, `${c.key}: three trees`);
  for (let ti = 0; ti < 3; ti++) {
    load(doc);
    W.pl_set_level(60);
    fill(doc, ti);
    const tree = doc.trees[ti];
    const max = tree.talents.reduce((s, t) => s + t.max, 0);
    assert.equal(W.pl_tree_points(ti), Math.min(51, max), `${c.key}/${tree.name}: can spend every point`);
    assert.equal(W.pl_validate(), 0);
    if (max >= 51) assert.equal(W.pl_can_add((ti + 1) % 3, 0), 3, 'budget is 51 points at level 60');

    // The build string restores exactly the same ranks.
    const code = exportCode();
    const ranks = tree.talents.map((_, i) => W.pl_rank(ti, i));
    assert.equal(importCode(code), 0, `${c.key}/${tree.name}: import ${code}`);
    assert.deepEqual(tree.talents.map((_, i) => W.pl_rank(ti, i)), ranks);

    // With exactly 5 points in row 1 and one in row 2, row 1 cannot give a point back.
    load(doc);
    W.pl_set_level(60);
    tree.talents.forEach((t, i) => { if (t.row === 1) while (W.pl_tree_points(ti) < 5 && W.pl_add(ti, i) === 0); });
    const second = tree.talents.findIndex((t) => t.row === 2 && !t.req);
    assert.equal(W.pl_add(ti, second), 0, `${c.key}/${tree.name}: row 2 opens at 5 points`);
    const first = tree.talents.findIndex((t, i) => t.row === 1 && W.pl_rank(ti, i) > 0);
    assert.equal(W.pl_can_remove(ti, first), 8, `${c.key}/${tree.name}: row 1 supports row 2`);

    // Level 30 gives 21 points.
    load(doc);
    W.pl_set_level(30);
    fill(doc, ti);
    assert.equal(W.pl_points_spent(), 21);
    assert.equal(W.pl_required_level(), 30);
  }
  for (const [name, values] of Object.entries(doc.tables)) assert.equal(values.length, 60, `${c.key}.${name}`);
}
console.log(`wasm engine ok for ${manifest.classes.length} classes`);
