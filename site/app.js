/* WoW Forever talent planner: UI.
 * All talent rules and stat maths run in the C engine (core/planner.c, built to
 * planner.wasm). This file loads data into it and draws what it reports. */
(() => {
  'use strict';

  // Mirrors of the enums in core/planner.h.
  const TABLES = ['agi_per_crit', 'int_per_spell_crit', 'base_mana'];
  const C = { AP_PER_STR: 0, AP_PER_AGI: 1, RAP_PER_AGI: 2, HP_PER_STA: 3, MANA_PER_INT: 4,
              STAT_FLOOR: 5, ARMOR_PER_AGI: 6, AP_PER_DPS: 7, STR_PER_BLOCK: 8 };
  const ATTRS = [['str', 'Strength'], ['agi', 'Agility'], ['sta', 'Stamina'], ['int', 'Intellect'], ['spi', 'Spirit']];
  const MODS = ['str_pct', 'agi_pct', 'sta_pct', 'int_pct', 'spi_pct', 'health_pct', 'mana_pct', 'crit', 'spell_crit'];
  const D = { STR: 0, AGI: 1, STA: 2, INT: 3, SPI: 4, HEALTH: 5, MANA: 6, AP: 7, RAP: 8, CRIT: 9,
              SPELL_CRIT: 10, ARMOR: 11, BLOCK: 12, DPS: 13 };
  const REASONS = {
    2: 'Already at max rank.',
    3: 'No talent points left at this level.',
    4: 'Spend more points in the rows above first.',
    5: 'Needs its prerequisite at max rank.',
    6: 'No points here to remove.',
    7: 'Another talent you have learned requires this one.',
    8: 'Talents further down the tree rely on these points.',
  };
  const INLINE = window.WF_INLINE || null;
  const $ = (sel) => document.querySelector(sel);

  let W = null;            // wasm exports
  let manifest = null;
  let doc = null;          // current class document
  const S = { cls: null, level: 60, tab: 0, selected: null, codes: {}, attrs: {} };
  const nodes = [];        // nodes[tree][talent] = button

  // ------------------------------------------------------------ small helpers

  function h(tag, props, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'style') e.style.cssText = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }

  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key) || 'null');
      localStorage.setItem(key, JSON.stringify(value));
    } catch (_) { /* storage is a convenience only */ }
    return null;
  }

  let toastTimer = 0;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }

  const fmt = (v, digits = 0) => Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const signed = (v, unit) => (v > 0 ? '+' : '') + fmt(v, Number.isInteger(v) ? 0 : 1) + unit;

  // ------------------------------------------------------------ data + engine

  async function loadJSON(name) {
    if (INLINE) return INLINE.data[name];
    const r = await fetch(`data/${name}.json`, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`Could not load data/${name}.json (${r.status})`);
    return r.json();
  }

  async function loadWasm() {
    let bytes;
    if (INLINE) bytes = Uint8Array.from(atob(INLINE.wasm), (c) => c.charCodeAt(0));
    else {
      const r = await fetch('planner.wasm');
      if (!r.ok) throw new Error(`Could not load planner.wasm (${r.status})`);
      bytes = await r.arrayBuffer();
    }
    W = (await WebAssembly.instantiate(bytes, {})).instance.exports;
  }

  function ioWrite(str) {
    const mem = new Uint8Array(W.memory.buffer, W.pl_io(), 1024);
    const s = str.slice(0, 1023);
    for (let i = 0; i < s.length; i++) mem[i] = s.charCodeAt(i) & 0x7f;
    mem[s.length] = 0;
  }
  function exportCode() {
    const len = W.pl_export();
    return String.fromCharCode(...new Uint8Array(W.memory.buffer, W.pl_io(), len));
  }
  function importCode(code) {
    ioWrite(code);
    return W.pl_import() === 0;
  }

  function loadEngine() {
    const r = manifest.rules, cv = manifest.conversions, k = doc.consts;
    W.pl_reset();
    W.pl_set_rules(r.first_point_level, r.max_level, r.points_per_row);
    doc.trees.forEach((tree) => {
      const ti = W.pl_add_tree();
      const index = new Map(tree.talents.map((t, i) => [t.name, i]));
      tree.talents.forEach((t) => W.pl_add_talent(ti, t.row, t.col, t.max, -1));
      tree.talents.forEach((t, i) => { if (t.req) W.pl_set_req(ti, i, index.get(t.req)); });
    });
    TABLES.forEach((name, ti) => (doc.tables[name] || []).forEach((v, i) => W.pl_table_set(ti, i + 1, v)));
    W.pl_const_set(C.AP_PER_STR, k.ap_per_str);
    W.pl_const_set(C.AP_PER_AGI, k.ap_per_agi);
    W.pl_const_set(C.RAP_PER_AGI, k.rap_per_agi);
    W.pl_const_set(C.HP_PER_STA, cv.health_per_stamina);
    W.pl_const_set(C.MANA_PER_INT, cv.mana_per_intellect);
    W.pl_const_set(C.STAT_FLOOR, cv.stat_floor);
    W.pl_const_set(C.ARMOR_PER_AGI, cv.armor_per_agility);
    W.pl_const_set(C.AP_PER_DPS, cv.attack_power_per_dps);
    W.pl_const_set(C.STR_PER_BLOCK, k.block_value ? cv.strength_per_block_value : 0);
  }

  /** Learned talents as [{tree, ti, t, i, rank}]. */
  function learned() {
    const out = [];
    doc.trees.forEach((tree, ti) => tree.talents.forEach((t, i) => {
      const rank = W.pl_rank(ti, i);
      if (rank) out.push({ tree, ti, t, i, rank });
    }));
    return out;
  }

  /** Re-apply a build saved by talent name; returns how many points could not be placed. */
  function loadByNames(ranks) {
    W.pl_clear_all();
    let wanted = 0, progress = true;
    Object.values(ranks).forEach((v) => { wanted += v; });
    while (progress) {
      progress = false;
      doc.trees.forEach((tree, ti) => tree.talents.forEach((t, i) => {
        const target = Math.min(ranks[`${tree.name}/${t.name}`] || 0, t.max);
        while (W.pl_rank(ti, i) < target && W.pl_add(ti, i) === 0) progress = true;
      }));
    }
    return wanted - W.pl_points_spent();
  }

  // ------------------------------------------------------------ rank text

  /** Pick out rank r from "+1/2/3%" lists and "3-15%" ranges in a summary. Marked with \u0001..\u0002. */
  function atRank(text, r, max) {
    if (max <= 1) return text;
    const mark = (v) => `\u0001${v}\u0002`;
    let out = text.replace(/([+-]?\d+(?:\.\d+)?)((?:\/[+-]?\d+(?:\.\d+)?)+)/g, (m, first, rest) => {
      const parts = (first + rest).split('/');
      if (parts.length !== max) return m;
      let v = parts[r - 1];
      const sign = /^[+-]/.test(parts[0]) ? parts[0][0] : '';
      if (sign && !/^[+-]/.test(v)) v = sign + v;
      return mark(v);
    });
    if (max >= 3) {
      out = out.replace(/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)/g, (m, a, b) => {
        if (Math.abs(a * max - b) > 1e-6) return m;
        return mark((a * r).toFixed((a.split('.')[1] || b.split('.')[1] || '').length));
      });
    }
    return out;
  }
  function marked(text) {
    return text.split(/[\u0001\u0002]/).map((part, i) => (i % 2 ? h('b', null, part) : part));
  }
  /** What a talent does at a given rank (rank 0 = the general description). */
  function talentText(t, rank) {
    if (t.ranks) return [t.ranks[Math.max(rank, 1) - 1]];
    const text = t.summary || '';
    return rank ? marked(atRank(text, rank, t.max)) : [text];
  }

  // ------------------------------------------------------------ class + level

  async function selectClass(key, code, level) {
    if (S.cls && W) S.codes[S.cls] = exportCode();
    doc = await loadJSON(key);
    S.cls = key;
    S.selected = null;
    S.tab = 0;
    loadEngine();
    if (level) S.level = level;
    W.pl_set_level(S.level);
    const restore = code != null ? code : S.codes[key];
    if (restore && !importCode(restore)) toast('That build does not fit the current talent data, so it was cleared.');
    document.documentElement.style.setProperty('--class', doc.color);
    document.querySelectorAll('#classes button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.key === key)));
    const src = doc.source;
    $('#build-line').textContent = `${doc.name} data from game build ${src.build || 'unknown'}, published ${src.generated || 'unknown'}`;
    buildTrees();
    buildStatsShell();
    refresh();
  }

  function setLevel(level) {
    S.level = level;
    W.pl_set_level(level);
    $('#level').value = level;
    refresh();
  }

  // ------------------------------------------------------------ trees

  function buildTrees() {
    const host = $('#trees');
    host.replaceChildren();
    nodes.length = 0;
    doc.trees.forEach((tree, ti) => {
      nodes.push([]);
      const rows = Math.max(...tree.talents.map((t) => t.row));
      const grid = h('div', { class: 'grid', style: `grid-template-rows: repeat(${rows}, var(--cell-h))` });
      grid.append(document.createElementNS('http://www.w3.org/2000/svg', 'svg'));
      tree.talents.forEach((t, i) => {
        const b = h('button', {
          type: 'button', class: 'node' + (t.cost ? ' active-ability' : ''),
          style: `grid-row:${t.row};grid-column:${t.col}`,
          onclick: () => onNode(ti, i),
          oncontextmenu: (e) => { e.preventDefault(); select(ti, i); change(ti, i, -1); },
          onkeydown: (e) => {
            if (e.key === '+' || e.key === '=') { select(ti, i); change(ti, i, 1); }
            if (e.key === '-' || e.key === 'Backspace' || e.key === 'Delete') { select(ti, i); change(ti, i, -1); }
          },
        }, h('span', { class: 'name' }, t.name), h('span', { class: 'rank' }));
        nodes[ti].push(b);
        grid.append(b);
      });
      host.append(h('section', { class: 'tree', 'data-tree': ti, 'aria-label': tree.name },
        h('div', { class: 'tree-head' },
          h('h2', null, tree.name),
          h('span', { class: 'num', id: `tree-points-${ti}` }),
          h('button', { type: 'button', onclick: () => { W.pl_clear_tree(ti); refresh(); } }, 'Clear')),
        grid));
    });
    host.append(h('p', { class: 'hint' }, 'Select a talent to read it. Select it again, or press +, to spend a point. Right-click or press − to take one back.'));
  }

  function drawArrows(ti) {
    const tree = doc.trees[ti];
    const grid = nodes[ti][0].parentElement;
    const svg = grid.querySelector('svg');
    const cs = getComputedStyle(grid);
    const cw = parseFloat(cs.getPropertyValue('--cell-w')), ch = parseFloat(cs.getPropertyValue('--cell-h'));
    const gx = parseFloat(cs.getPropertyValue('--gap-x')), gy = parseFloat(cs.getPropertyValue('--gap-y'));
    const cx = (t) => (t.col - 1) * (cw + gx) + cw / 2, cy = (t) => (t.row - 1) * (ch + gy) + ch / 2;
    const index = new Map(tree.talents.map((t, i) => [t.name, i]));
    let out = '';
    tree.talents.forEach((t) => {
      if (!t.req) return;
      const ri = index.get(t.req), req = tree.talents[ri];
      const met = W.pl_rank(ti, ri) >= req.max ? ' class="met"' : '';
      const x1 = cx(req), y1 = cy(req), x2 = cx(t), y2 = cy(t), dir = Math.sign(x2 - x1);
      let d, tip;
      if (t.row === req.row) {
        d = `M${x1 + dir * cw / 2},${y1}H${x2 - dir * cw / 2}`;
        tip = [x2 - dir * cw / 2, y2, dir, 0];
      } else if (t.col === req.col) {
        d = `M${x1},${y1 + ch / 2}V${y2 - ch / 2}`;
        tip = [x2, y2 - ch / 2, 0, 1];
      } else {
        d = `M${x1 + dir * cw / 2},${y1}H${x2}V${y2 - ch / 2}`;
        tip = [x2, y2 - ch / 2, 0, 1];
      }
      const [tx, ty, dx, dy] = tip;
      const head = `M${tx},${ty}L${tx - dx * 7 - dy * 5},${ty - dy * 7 - dx * 5}L${tx - dx * 7 + dy * 5},${ty - dy * 7 + dx * 5}Z`;
      out += `<path${met} d="${d}"/><path${met} d="${head}"/>`;
    });
    svg.innerHTML = out;
  }

  function select(ti, i) {
    S.selected = { ti, i };
    S.tab = ti;
  }
  function change(ti, i, delta) {
    const code = delta > 0 ? W.pl_add(ti, i) : W.pl_remove(ti, i);
    refresh();
    if (code !== 0 && REASONS[code]) toast(REASONS[code]);
  }
  function onNode(ti, i) {
    const again = S.selected && S.selected.ti === ti && S.selected.i === i;
    select(ti, i);
    if (again) change(ti, i, 1); else refresh();
  }

  function renderTrees() {
    const tabs = $('#tree-tabs');
    tabs.replaceChildren(...doc.trees.map((tree, ti) => h('button', {
      type: 'button', 'aria-pressed': String(S.tab === ti),
      onclick: () => { S.tab = ti; refresh(); },
    }, tree.name + ' ', h('span', { class: 'num' }, W.pl_tree_points(ti)))));
    doc.trees.forEach((tree, ti) => {
      nodes[ti][0].closest('.tree').classList.toggle('current', S.tab === ti);
      $(`#tree-points-${ti}`).textContent = `${W.pl_tree_points(ti)} points`;
      tree.talents.forEach((t, i) => {
        const b = nodes[ti][i], rank = W.pl_rank(ti, i);
        const sel = S.selected && S.selected.ti === ti && S.selected.i === i;
        b.classList.toggle('learned', rank > 0);
        b.classList.toggle('maxed', rank >= t.max);
        b.classList.toggle('open', rank < t.max && W.pl_can_add(ti, i) === 0);
        b.classList.toggle('selected', !!sel);
        b.lastChild.textContent = `${rank}/${t.max}`;
        b.setAttribute('aria-label', `${t.name}, rank ${rank} of ${t.max}`);
      });
      drawArrows(ti);
    });
  }

  function renderDetail() {
    const box = $('#detail');
    if (!S.selected) {
      box.replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, 'No talent selected.'));
      return;
    }
    const { ti, i } = S.selected, t = doc.trees[ti].talents[i], rank = W.pl_rank(ti, i);
    const canAdd = W.pl_can_add(ti, i), canRemove = W.pl_can_remove(ti, i);
    const lines = [];
    if (t.cost && t.cost !== 'Active') lines.push(h('p', { class: 'cost' }, t.cost));
    if (rank === 0) lines.push(h('p', null, talentText(t, 0)));
    else {
      lines.push(h('p', null, h('span', { class: 'muted' }, t.max > 1 ? `Rank ${rank}: ` : ''), talentText(t, rank)));
      if (rank < t.max) lines.push(h('p', { class: 'muted' }, `Rank ${rank + 1}: `, talentText(t, rank + 1)));
    }
    const row = manifest.rules.points_per_row * (t.row - 1);
    if (canAdd === 4) lines.push(h('p', { class: 'warn' }, `Needs ${row} points in the rows above (row ${t.row}).`));
    else if (canAdd === 5) lines.push(h('p', { class: 'warn' }, `Needs ${t.req} at max rank.`));
    else if (canAdd === 3) lines.push(h('p', { class: 'warn' }, REASONS[3]));
    else if (t.req) lines.push(h('p', { class: 'muted' }, `Requires ${t.req}.`));
    if (rank > 0 && canRemove !== 0) lines.push(h('p', { class: 'muted' }, REASONS[canRemove]));
    box.replaceChildren(
      h('div', { class: 'detail-head' },
        h('h2', null, t.name),
        h('span', { class: 'rank' }, `${rank}/${t.max}`),
        h('button', { type: 'button', 'aria-label': 'Remove a point', disabled: canRemove !== 0, onclick: () => change(ti, i, -1) }, '−'),
        h('button', { type: 'button', 'aria-label': 'Spend a point', disabled: canAdd !== 0, onclick: () => change(ti, i, 1) }, '+')),
      lines);
  }

  // ------------------------------------------------------------ level bar

  function renderPoints() {
    const avail = W.pl_points_at_level(S.level), spent = W.pl_points_spent(), left = W.pl_points_left();
    $('#level-out').textContent = S.level;
    const split = doc.trees.map((_, ti) => W.pl_tree_points(ti)).join(' / ');
    const first = manifest.rules.first_point_level;
    const parts = [h('strong', null, spent), ` of ${avail} points spent (${split})`];
    if (left < 0) parts.push(h('span', { class: 'warn' }, `. This build needs level ${W.pl_required_level()}.`));
    else if (avail === 0) parts.push(`. Talent points start at level ${first}.`);
    else parts.push(`, ${left} left`);
    $('#points').replaceChildren(...parts);
  }

  // ------------------------------------------------------------ bonuses

  function statTotals() {
    const totals = new Map();
    learned().forEach(({ t, rank }) => (t.effects || []).forEach((e) => {
      const key = e.stat + '|' + (e.scope || '');
      const cur = totals.get(key) || { stat: e.stat, scope: e.scope || '', value: 0, from: [] };
      cur.value += e.values[rank - 1];
      cur.from.push(t.name);
      totals.set(key, cur);
    }));
    return [...totals.values()];
  }

  function renderBonuses() {
    const box = $('#bonuses'), all = learned();
    if (!all.length) {
      box.replaceChildren(h('p', { class: 'muted' }, 'Spend talent points and every bonus they give is listed here, with stat boosts added up across trees.'));
      return;
    }
    const kids = [];
    const totals = statTotals();
    if (totals.length) {
      kids.push(h('h3', null, 'Stat totals'), h('table', null, h('tbody', null, totals.map((x) => {
        const def = manifest.stats[x.stat];
        return h('tr', null,
          h('td', null, def.label, x.scope ? h('span', { class: 'muted' }, ` (${x.scope})`) : null,
            h('div', { class: 'muted', style: 'font-size:0.8rem' }, x.from.join(', '))),
          h('td', { class: 'num total-value' }, signed(x.value, def.unit)));
      }))));
    }
    const abilities = all.filter((x) => x.t.cost);
    if (abilities.length) {
      kids.push(h('h3', null, 'Abilities unlocked'), h('ul', { class: 'taken' }, abilities.map(({ t }) => h('li', null,
        h('span', { class: 't-name' }, t.name),
        h('span', { class: 't-text' }, talentText(t, 1), t.cost !== 'Active' ? ` (${t.cost})` : '')))));
    }
    doc.trees.forEach((tree, ti) => {
      const mine = all.filter((x) => x.ti === ti && !x.t.cost);
      if (!mine.length) return;
      kids.push(h('h3', null, `${tree.name} passives`), h('ul', { class: 'taken' }, mine.map(({ t, rank }) => h('li', null,
        h('span', { class: 't-name' }, t.name), h('span', { class: 't-rank' }, `${rank}/${t.max}`),
        h('span', { class: 't-text' }, talentText(t, rank))))));
    });
    box.replaceChildren(...kids);
  }

  // ------------------------------------------------------------ base stats

  function buildStatsShell() {
    const saved = (store('wfplanner.attrs') || {})[S.cls];
    S.attrs = saved || { str: 100, agi: 100, sta: 100, int: 100, spi: 100 };
    $('#stats').replaceChildren(
      h('div', { id: 'stats-level' }),
      h('h3', null, 'Your attributes'),
      h('div', { class: 'attrs' }, ATTRS.map(([key, label]) => h('label', { for: `attr-${key}` }, label,
        h('input', {
          id: `attr-${key}`, type: 'number', min: 0, max: 9999, inputmode: 'numeric', value: S.attrs[key],
          oninput: (e) => {
            S.attrs[key] = Math.max(0, Number(e.target.value) || 0);
            const all = store('wfplanner.attrs') || {};
            all[S.cls] = S.attrs;
            store('wfplanner.attrs', all);
            renderDerived();
          },
        })))),
      h('p', { class: 'note', style: 'margin-top:8px' }, saved ? 'Totals from your character sheet, gear included.'
        : 'These are example numbers. Replace them with the totals on your character sheet, gear included.'),
      h('div', { id: 'stats-derived' }),
      h('p', { class: 'note', style: 'margin-top:12px' },
        'The game client does not publish base Strength, Agility, Stamina, Intellect, Spirit or base health per level, ',
        'nor base crit, dodge per Agility or Spirit regeneration, so those are not shown.'));
  }

  function renderStatsLevel() {
    const r = manifest.rules, cv = manifest.conversions, k = doc.consts, tb = doc.tables;
    const picks = [...new Set([1, 10, 20, 30, 40, 50, 60, S.level])].sort((a, b) => a - b);
    const cols = [['Level', (l) => l], ['Points', (l) => W.pl_points_at_level(l)]];
    if (tb.agi_per_crit) cols.push(['Agi per 1% crit', (l) => fmt(tb.agi_per_crit[l - 1], 1)]);
    if (tb.int_per_spell_crit) cols.push(['Int per 1% spell crit', (l) => fmt(tb.int_per_spell_crit[l - 1], 1)]);
    if (tb.base_mana) cols.push(['Base mana', (l) => fmt(tb.base_mana[l - 1])]);
    const facts = [
      ['Attack power per Strength', k.ap_per_str],
      k.ap_per_agi ? ['Attack power per Agility', k.ap_per_agi] : null,
      k.rap_per_agi ? ['Ranged attack power per Agility', k.rap_per_agi] : null,
      ['Health per Stamina', `${cv.health_per_stamina} (1 each for the first ${cv.stat_floor})`],
      tb.base_mana ? ['Mana per Intellect', `${cv.mana_per_intellect} (1 each for the first ${cv.stat_floor})`] : null,
      ['Armor per Agility', cv.armor_per_agility],
      k.block_value ? ['Strength per 1 block value', cv.strength_per_block_value] : null,
      ['Attack power per 1 weapon DPS', cv.attack_power_per_dps],
      ['Rating for 1%', Object.entries(cv.rating_per_percent).map(([n, v]) => `${n} ${v}`).join(', ')],
    ].filter(Boolean);
    $('#stats-level').replaceChildren(
      h('h3', { style: 'margin-top:0' }, `${doc.name} by level`),
      h('div', { class: 'scroll' }, h('table', null,
        h('thead', null, h('tr', null, cols.map(([name], ci) => h('th', { class: ci ? 'num' : null }, name)))),
        h('tbody', null, picks.map((l) => h('tr', { class: l === S.level ? 'now' : null },
          cols.map(([, get], ci) => h('td', { class: ci ? 'num' : null }, get(l)))))))),
      h('p', { class: 'note', style: 'margin-top:8px' },
        `The highlighted row follows the level slider. First talent point at level ${r.first_point_level}, one per level after that.`),
      h('h3', null, 'What a point gives'),
      h('table', null, h('tbody', null, facts.map(([name, v]) => h('tr', null, h('td', null, name), h('td', { class: 'num' }, v))))));
  }

  function renderDerived() {
    const totals = statTotals(), applied = [];
    MODS.forEach((name, mi) => {
      const hit = totals.find((x) => x.stat === name && !x.scope);
      W.pl_mod_set(mi, hit ? hit.value : 0);
      if (hit) applied.push(`${manifest.stats[name].label} ${signed(hit.value, manifest.stats[name].unit)}`);
    });
    ATTRS.forEach(([key], ai) => W.pl_attr_set(ai, S.attrs[key] || 0));
    const d = (which) => W.pl_derived(which), k = doc.consts;
    const rows = [];
    ATTRS.forEach(([key, label], ai) => { if (d(ai) !== (S.attrs[key] || 0)) rows.push([`${label} after talents`, fmt(d(ai))]); });
    rows.push(['Attack power from attributes', fmt(d(D.AP))]);
    if (k.rap_per_agi) rows.push(['Ranged attack power from Agility', fmt(d(D.RAP))]);
    rows.push(['Weapon DPS from that attack power', fmt(d(D.DPS), 1)]);
    rows.push(['Crit from Agility and talents', fmt(d(D.CRIT), 2) + '%']);
    if (d(D.SPELL_CRIT) >= 0) rows.push(['Spell crit from Intellect and talents', fmt(d(D.SPELL_CRIT), 2) + '%']);
    rows.push(['Health from Stamina', fmt(d(D.HEALTH))]);
    if (d(D.MANA) >= 0) rows.push(['Mana (base plus Intellect)', fmt(d(D.MANA))]);
    rows.push(['Armor from Agility', fmt(d(D.ARMOR))]);
    if (d(D.BLOCK) >= 0) rows.push(['Block value from Strength', fmt(d(D.BLOCK))]);
    $('#stats-derived').replaceChildren(
      h('h3', null, `What they give at level ${S.level}`),
      h('table', null, h('tbody', null, rows.map(([name, v]) => h('tr', null, h('td', null, name), h('td', { class: 'num total-value' }, v))))),
      h('p', { class: 'note', style: 'margin-top:8px' }, applied.length
        ? `Talents applied: ${applied.join(', ')}.`
        : 'No talent in this build changes these numbers yet.'));
  }

  // ------------------------------------------------------------ saved builds + data notes

  function renderData() {
    const builds = store('wfplanner.builds') || [];
    const nameInput = h('input', { id: 'build-name', type: 'text', maxlength: 40, placeholder: 'Name this build', 'aria-label': 'Build name' });
    const save = () => {
      const all = learned();
      if (!all.length) return toast('Spend some points first.');
      const ranks = {};
      all.forEach(({ tree, t, rank }) => { ranks[`${tree.name}/${t.name}`] = rank; });
      const split = doc.trees.map((_, ti) => W.pl_tree_points(ti)).join('/');
      builds.unshift({ name: nameInput.value.trim() || `${doc.name} ${split}`, cls: S.cls, level: S.level, split, ranks, build: doc.source.build });
      store('wfplanner.builds', builds.slice(0, 50));
      renderData();
      toast('Build saved in this browser.');
    };
    const list = builds.map((b, bi) => h('li', null,
      h('span', { class: 'b-name' }, b.name, h('span', { class: 'muted' }, ` ${manifest.classes.find((c) => c.key === b.cls)?.name || b.cls} ${b.split}, level ${b.level}`)),
      h('button', { type: 'button', onclick: async () => {
        await selectClass(b.cls, '', b.level);
        $('#level').value = b.level;
        const lost = loadByNames(b.ranks);
        refresh();
        toast(lost ? `Loaded, but ${lost} point${lost === 1 ? '' : 's'} no longer fit the current talent data.` : 'Build loaded.');
      } }, 'Load'),
      h('button', { type: 'button', 'aria-label': `Delete ${b.name}`, onclick: () => { builds.splice(bi, 1); store('wfplanner.builds', builds); renderData(); } }, 'Delete')));
    const src = manifest.sources;
    const log = manifest.changelog || [];
    $('#data').replaceChildren(
      h('form', { class: 'save-row', onsubmit: (e) => { e.preventDefault(); save(); } }, nameInput, h('button', { type: 'submit' }, 'Save build')),
      builds.length ? h('ul', { class: 'builds' }, list)
        : h('p', { class: 'note', style: 'margin-top:8px' }, 'Saved builds stay in this browser. They are stored by talent name, so they survive game data updates.'),
      h('h3', null, 'Game data in use'),
      h('div', { class: 'scroll' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, 'Class'), h('th', null, 'Game build'), h('th', null, 'Published'))),
        h('tbody', null, manifest.classes.map((c) => h('tr', { class: c.key === S.cls ? 'now' : null },
          h('td', null, c.name), h('td', { class: 'num', style: 'text-align:left' }, c.build || '?'), h('td', { class: 'num', style: 'text-align:left' }, c.generated || '?')))))),
      h('p', { class: 'note', style: 'margin-top:8px' },
        'Talent data from ', h('a', { href: src.talents.url }, src.talents.name), `, licensed ${src.talents.license}. `,
        'Per-level stat tables from ', h('a', { href: src.stats.url }, src.stats.name), ` (build ${src.stats.build}). `,
        'Game names and tooltip text belong to Blizzard Entertainment. This planner is not affiliated with Blizzard.'),
      manifest.classes.some((c) => (c.method || '').startsWith('seed'))
        ? h('p', { class: 'note' }, 'Talent descriptions are short summaries for now. Running the data update replaces them with the full text for every rank.')
        : null,
      manifest.rules.assumed && manifest.rules.assumed.length
        ? h('p', { class: 'note' }, `Assumed from Classic until confirmed: ${manifest.rules.points_per_row} points per row to unlock the next one, and prerequisites need max rank.`)
        : null,
      h('h3', null, 'Data updates'),
      log.length ? h('ul', { class: 'changelog' }, log.slice(0, 5).map((entry) => {
        const n = Object.values(entry.classes || {}).reduce((sum, lines) => sum + lines.length, 0);
        return h('li', null, `${entry.date}: ${n} change${n === 1 ? '' : 's'} in ${Object.keys(entry.classes || {}).map((c) => c.replace('_', '')).join(', ') || 'build numbers only'}`);
      })) : h('p', { class: 'note' }, `No updates recorded since the data was first added (${manifest.built}).`));
  }

  // ------------------------------------------------------------ refresh + start

  function refresh() {
    renderPoints();
    renderTrees();
    renderDetail();
    renderBonuses();
    renderStatsLevel();
    renderDerived();
    renderData();
    try { history.replaceState(null, '', `#${S.cls}-${S.level}-${exportCode()}`); } catch (_) { /* sandboxed frame */ }
  }

  function parseHash() {
    const parts = location.hash.replace(/^#/, '').split('-');
    if (!manifest.classes.some((c) => c.key === parts[0])) return null;
    const level = Math.min(Math.max(parseInt(parts[1], 10) || 60, 1), manifest.rules.max_level);
    return { cls: parts[0], level, code: parts.slice(2).join('-') };
  }

  async function start() {
    try {
      [manifest] = await Promise.all([loadJSON('manifest'), loadWasm()]);
    } catch (err) {
      $('#build-line').textContent = `${err.message}. If you opened index.html straight from disk, run "make serve" instead.`;
      $('#build-line').classList.add('warn');
      return;
    }
    $('#level').max = manifest.rules.max_level;
    $('#classes').replaceChildren(...manifest.classes.map((c) => h('button', {
      type: 'button', 'data-key': c.key, style: `--c:${c.color}`, 'aria-pressed': 'false',
      onclick: () => selectClass(c.key),
    }, c.name)));
    $('#level').addEventListener('input', (e) => setLevel(Number(e.target.value)));
    $('#reset-all').addEventListener('click', () => { W.pl_clear_all(); S.selected = null; refresh(); });
    $('#copy-link').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(location.href); toast('Link to this build copied.'); }
      catch (_) { toast('Copy the address bar to share this build.'); }
    });
    document.querySelectorAll('#views button').forEach((b) => b.addEventListener('click', () => {
      $('#app').dataset.view = b.dataset.view;
      document.querySelectorAll('#views button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    }));
    window.addEventListener('resize', () => doc && doc.trees.forEach((_, ti) => drawArrows(ti)));
    window.addEventListener('hashchange', () => {
      const want = parseHash();
      if (want && `#${S.cls}-${S.level}-${exportCode()}` !== location.hash) {
        $('#level').value = want.level;
        selectClass(want.cls, want.code, want.level);
      }
    });
    const from = parseHash() || { cls: manifest.classes[0].key, level: manifest.rules.max_level, code: null };
    $('#level').value = from.level;
    await selectClass(from.cls, from.code, from.level);
  }

  start();
})();
