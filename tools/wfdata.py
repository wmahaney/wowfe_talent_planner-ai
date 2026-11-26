#!/usr/bin/env python3
"""Data pipeline for the WoW Forever talent planner.

Canonical data lives in data/ (one JSON file per class plus stats, rules and
curated effects). The site reads the generated copies in site/data/.

    python3 tools/wfdata.py seed      # rebuild data/talents + data/stats.json from data/seed
    python3 tools/wfdata.py update    # pull the latest game data, write a changelog entry
    python3 tools/wfdata.py build     # regenerate site/data from data/
    python3 tools/wfdata.py check     # validate data/ without writing anything
    python3 tools/wfdata.py icons     # download the icon images into site/icons/

`update` is what you run (or what the scheduled GitHub workflow runs) after a
game patch or hotfix. It only needs the Python standard library.
"""
import argparse
import datetime
import hashlib
import html.parser
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"
CLASSES = ["warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid"]
SCHEMA = 1

TALENT_SOURCE = {
    "name": "Talents Forever",
    "url": "https://talentsforever.com/",
    "export": "https://talentsforever.com/export/{cls}.json",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "Talent data from Talents Forever (https://talentsforever.com/), licensed CC BY 4.0. "
                   "Game names and tooltip text belong to Blizzard Entertainment.",
    "changes": "Reformatted into this project's JSON; descriptions may be summarised; "
               "per-rank and per-level values are computed from the text. See CREDITS.md.",
}
STATS_SOURCE = {
    "name": "ForeverDB",
    "url": "https://foreverdb.net/stats",
    "page": "https://foreverdb.net/stats/{cls}",
    "license": "none stated",
}
STAT_TABLES = ["agi_per_crit", "int_per_spell_crit", "base_mana"]
BUILD_RE = re.compile(r"\b\d+\.\d+\.\d+\.\d{4,6}\b")


# ---------------------------------------------------------------- helpers

def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, obj, compact=False):
    if isinstance(obj, dict) and isinstance(obj.get("source"), dict) and obj["source"].get("name") == TALENT_SOURCE["name"]:
        obj["source"].update({k: TALENT_SOURCE[k] for k in ("license_url", "attribution", "changes")})
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def today():
    return datetime.date.today().isoformat()


def text_hash(ranks):
    return hashlib.sha1("\n".join(ranks).encode("utf-8")).hexdigest()[:12]


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "wow_forever_talent_planner-ai data updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------- validation

def validate_class(doc):
    """Return a list of problems with one class document (empty = fine)."""
    problems = []
    rules = read_json(DATA / "rules.json")["talents"]
    for tree in doc["trees"]:
        seen_pos, names = {}, {}
        for t in tree["talents"]:
            where = f'{doc["class"]}/{tree["name"]}/{t["name"]}'
            if t["name"] in names:
                problems.append(f"{where}: duplicate talent name")
            names[t["name"]] = t
            pos = (t["row"], t["col"])
            if pos in seen_pos:
                problems.append(f'{where}: shares row {pos[0]} col {pos[1]} with {seen_pos[pos]}')
            seen_pos[pos] = t["name"]
            if not (1 <= t["row"] <= 11 and 1 <= t["col"] <= 4):
                problems.append(f"{where}: position out of range")
            if not (1 <= t["max"] <= 9):
                problems.append(f"{where}: max rank {t['max']} out of range")
            if t.get("ranks") and len(t["ranks"]) != t["max"]:
                problems.append(f"{where}: {len(t['ranks'])} rank texts for max rank {t['max']}")
        for t in tree["talents"]:
            if t.get("req"):
                where = f'{doc["class"]}/{tree["name"]}/{t["name"]}'
                req = names.get(t["req"])
                if req is None:
                    problems.append(f'{where}: requires unknown talent "{t["req"]}"')
                elif req is t or req["row"] > t["row"]:
                    problems.append(f'{where}: requires "{t["req"]}", which sits in a later row')
        # Every row must be reachable: enough points available in the rows above it.
        by_row = {}
        for t in tree["talents"]:
            by_row[t["row"]] = by_row.get(t["row"], 0) + t["max"]
        for row in sorted(by_row):
            above = sum(v for r, v in by_row.items() if r < row)
            if above < rules["points_per_row"] * (row - 1):
                problems.append(f'{doc["class"]}/{tree["name"]}: row {row} can never be unlocked '
                                f'({above} points available above it)')
    for tab in (doc.get("spells") or {}).get("tabs", []):
        for sp in tab["spells"]:
            lv = sp.get("levels")
            if lv and (any(not 1 <= v <= 60 for v in lv) or lv != sorted(lv)):
                problems.append(f'{doc["class"]} spell {tab["name"]}/{sp["name"]}: odd learn levels {lv}')
    return problems


def load_effects():
    """data/effects.txt -> {class: {(tree, talent): [{stat, values, scope}]}}"""
    out = {c: {} for c in CLASSES}
    stats = read_json(DATA / "rules.json")["stats"]
    for n, line in enumerate((DATA / "effects.txt").read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) not in (5, 6):
            raise SystemExit(f"data/effects.txt:{n}: expected 5 or 6 fields")
        cls, tree, talent, stat, values = parts[:5]
        if cls not in out:
            raise SystemExit(f"data/effects.txt:{n}: unknown class {cls}")
        if stat not in stats:
            raise SystemExit(f"data/effects.txt:{n}: unknown stat {stat} (define it in data/rules.json)")
        eff = {"stat": stat, "values": [float(v) if "." in v else int(v) for v in values.split("/")]}
        if len(parts) == 6 and parts[5]:
            eff["scope"] = parts[5]
        out[cls].setdefault((tree, talent), []).append(eff)
    return out


def effects_review(cls, doc, effects, changed_text=()):
    """Curated effects that no longer line up with the talent data."""
    notes = []
    index = {(tr["name"], t["name"]): t for tr in doc["trees"] for t in tr["talents"]}
    for (tree, talent), effs in effects[cls].items():
        t = index.get((tree, talent))
        if t is None:
            notes.append(f"{cls}: effect for {tree}/{talent} points at a talent that no longer exists")
            continue
        for e in effs:
            if len(e["values"]) != t["max"]:
                notes.append(f"{cls}: effect {e['stat']} on {tree}/{talent} has {len(e['values'])} values "
                             f"but the talent has {t['max']} ranks")
        if (tree, talent) in changed_text:
            notes.append(f"{cls}: {tree}/{talent} changed text; re-check its curated effect")
    return notes


# ---------------------------------------------------------------- seed

def cmd_seed(args):
    for cls in CLASSES:
        path = DATA / "seed" / "talents" / f"{cls}.txt"
        build = generated = None
        trees, order = {}, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# class:"):
                meta = dict(p.strip().split(": ", 1) for p in line[1:].split("|"))
                build, generated = meta.get("build"), meta.get("generated")
                continue
            if not line.strip() or line.startswith("#"):
                continue
            tree, name, row, col, mx, req, cost, summary = line.split("|")
            if tree not in trees:
                trees[tree] = []
                order.append(tree)
            trees[tree].append({"name": name, "row": int(row), "col": int(col), "max": int(mx),
                                "req": req or None, "cost": cost or None, "summary": summary, "ranks": None})
        tabs, tab_order, general = {}, [], []
        for line in (DATA / "seed" / "extra" / f"{cls}.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            kind, a, b, *rest = line.split("|")
            if kind == "T":      # T|tree|talent|icon
                match = [t for t in trees[a] if t["name"] == b]
                if not match:
                    raise SystemExit(f"data/seed/extra/{cls}.txt: no talent {a}/{b}")
                match[0]["icon"] = rest[0]
            elif kind == "S":    # S|tab|spell|levels|icon
                if a not in tabs:
                    tabs[a] = []
                    tab_order.append(a)
                levels = None if rest[0] == "?" else [int(v) for v in rest[0].split(",")]
                tabs[a].append({"name": b, "levels": levels, "icon": rest[1] or None})
            elif kind == "G":    # G|name|note
                general.append({"name": a, "note": b or None})
        doc = {"schema": SCHEMA, "class": cls,
               "source": {"name": TALENT_SOURCE["name"], "url": TALENT_SOURCE["url"],
                          "license": TALENT_SOURCE["license"], "build": build, "generated": generated,
                          "retrieved": args.date, "method": "seed (hand-transcribed summaries)"},
               "trees": [{"name": t, "talents": trees[t]} for t in order],
               "spells": {"tabs": [{"name": t, "spells": tabs[t]} for t in tab_order], "general": general}}
        problems = validate_class(doc)
        if problems:
            raise SystemExit("\n".join(problems))
        write_json(DATA / "talents" / f"{cls}.json", doc)

    stats = {"schema": SCHEMA, "source": {"name": STATS_SOURCE["name"], "url": STATS_SOURCE["url"],
                                          "build": "1.60.1.70959", "retrieved": args.date}, "classes": {}}
    for line in (DATA / "seed" / "stats.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, values = line.split("=")
        cls, table = key.strip().split(".")
        nums = [float(v) for v in values.split()]
        if len(nums) != 60:
            raise SystemExit(f"data/seed/stats.txt: {key.strip()} has {len(nums)} values, expected 60")
        stats["classes"].setdefault(cls, {})[table] = nums
    write_json(DATA / "stats.json", stats)
    print("seeded data/talents and data/stats.json")
    cmd_build(args)


# ---------------------------------------------------------------- update: talents

def find_trees(node, key=None):
    """Find tree objects anywhere in a Talents Forever export.

    A tree is a dict with a "talents" list whose items carry name/row/col. The
    walk is deliberately loose so a reshuffled export still parses."""
    found = []
    if isinstance(node, dict):
        tl = node.get("talents")
        if isinstance(tl, list) and tl and all(isinstance(t, dict) and "row" in t and "col" in t and "name" in t
                                               for t in tl):
            found.append((node.get("name") or key or "?", node))
        else:
            for k, v in node.items():
                found.extend(find_trees(v, k))
    elif isinstance(node, list):
        for v in node:
            found.extend(find_trees(v, key))
    return found


def find_build(export):
    for k in ("build", "data_build"):
        if isinstance(export.get(k), str) and BUILD_RE.search(export[k]):
            return BUILD_RE.search(export[k]).group(0)
    for v in export.values():
        if isinstance(v, str):
            m = BUILD_RE.search(v)
            if m:
                return m.group(0)
    blob = json.dumps(export.get("talents", ""))[:20000]
    m = BUILD_RE.search(blob)
    return m.group(0) if m else None


def convert_spellbook(export):
    """The export's spellbook -> {"tabs": [...], "general": [...]}, or None if it has none.

    Multi-rank learn levels come from spellbook.levels; single-rank ones from the
    "Learned at level N" line of the matching spell_desc entry (key Class|Spell|Rank)."""
    book = export.get("spellbook")
    if not isinstance(book, dict) or not isinstance(book.get("tabs"), list):
        return None
    levels, icons = book.get("levels") or {}, book.get("icons") or {}
    desc_level = {}
    for key, entry in (export.get("spell_desc") or {}).items():
        parts = key.split("|")
        m = re.search(r"\d+", str(entry.get("lv", ""))) if isinstance(entry, dict) else None
        if len(parts) >= 2 and m:
            desc_level.setdefault(parts[1], []).append(int(m.group(0)))
    tabs = []
    for tab in book["tabs"]:
        spells, seen = [], set()
        for item in tab.get("spells", []):
            name = item[0] if isinstance(item, (list, tuple)) else item.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            lv = levels.get(name) or sorted(desc_level.get(name, [])) or None
            icon = icons.get(name)
            if isinstance(icon, list):
                icon = icon[0] if icon else None
            spells.append({"name": name, "levels": [int(v) for v in lv] if lv else None, "icon": icon or None})
        tabs.append({"name": tab.get("name", "?"), "spells": spells})
    general = []
    for item in book.get("general") or []:
        if isinstance(item, (list, tuple)) and item:
            general.append({"name": item[0], "note": (item[1] if len(item) > 1 else None) or None})
    return {"tabs": tabs, "general": general}


def convert_export(cls, export, old, date):
    trees = find_trees(export.get("talents", export))
    if len(trees) != 3:
        raise ValueError(f"{cls}: expected 3 talent trees in the export, found {len(trees)}")
    old_index = {}
    if old:
        old_index = {(tr["name"], t["name"]): t for tr in old["trees"] for t in tr["talents"]}
    out_trees = []
    for tree_name, tree in trees:
        talents = []
        for t in tree["talents"]:
            ranks = t.get("desc") or t.get("ranks") or []
            if isinstance(ranks, str):
                ranks = [ranks]
            ranks = [r if isinstance(r, str) else (r.get("text") or r.get("desc") or "") for r in ranks]
            mx = int(t.get("max", t.get("max_rank", len(ranks) or 1)))
            req = t.get("req", t.get("requires"))
            if isinstance(req, dict):
                req = req.get("name")
            if isinstance(req, list):
                req = (req[0].get("name") if isinstance(req[0], dict) else req[0]) if req else None
            prev = old_index.get((tree_name, t["name"]))
            summary = None
            if prev and prev.get("summary"):
                same_text = prev.get("ranks") is None or prev["ranks"] == ranks
                if same_text and prev["max"] == mx:
                    summary = prev["summary"]
            cost = t.get("cost") or None
            if cost is None and t.get("passive") is False:
                cost = "Active"
            talents.append({"name": t["name"], "row": int(t["row"]), "col": int(t["col"]), "max": mx,
                            "req": req or None, "cost": cost, "summary": summary,
                            "ranks": ranks if len(ranks) == mx else None,
                            "icon": t.get("icon") or (prev or {}).get("icon")})
        talents.sort(key=lambda x: (x["row"], x["col"]))
        out_trees.append({"name": tree_name, "talents": talents})
    return {"schema": SCHEMA, "class": cls,
            "source": {"name": TALENT_SOURCE["name"], "url": TALENT_SOURCE["url"],
                       "license": TALENT_SOURCE["license"], "build": find_build(export) or ((old or {}).get("source") or {}).get("build"),
                       "generated": export.get("generated"), "retrieved": date,
                       "method": "export"},
            "trees": out_trees,
            "spells": convert_spellbook(export) or (old or {}).get("spells") or {"tabs": [], "general": []}}


def _cost_key(cost):
    """Cost text reduced to its facts, so a change of punctuation or wording isn't news."""
    if not cost:
        return ()
    c = cost.lower().replace("|", ";").replace(" to ", "-")
    for word in ("range", "requires", "reagents:", "tools:", ":"):
        c = c.replace(word, " ")
    return tuple(sorted(" ".join(part.split()) for part in re.split(r"[;,]", c) if part.strip()))


def diff_changes(old, new):
    """Structured talent and spell changes between two class documents.

    Each change is {"kind", "tree", "name", "from", "to"} plus "minor": true for
    changes that are only rewording. The site's Updates view reads these.
    """
    out = []
    if old is None:
        return [{"kind": "new_class"}]
    o = {(tr["name"], t["name"]): t for tr in old["trees"] for t in tr["talents"]}
    n = {(tr["name"], t["name"]): t for tr in new["trees"] for t in tr["talents"]}
    def rank_text(t):
        return (t.get("ranks") or [None])[-1] or t.get("summary")
    for key in sorted(n.keys() - o.keys()):
        t = n[key]
        out.append({"kind": "added", "tree": key[0], "name": key[1],
                    "to": {"row": t["row"], "col": t["col"], "max": t["max"], "text": rank_text(t)}})
    for key in sorted(o.keys() - n.keys()):
        out.append({"kind": "removed", "tree": key[0], "name": key[1], "from": {"text": rank_text(o[key])}})
    for key in sorted(n.keys() & o.keys()):
        a, b = o[key], n[key]
        base = {"tree": key[0], "name": key[1]}
        if (a["row"], a["col"]) != (b["row"], b["col"]):
            out.append({**base, "kind": "moved", "from": [a["row"], a["col"]], "to": [b["row"], b["col"]]})
        if a["max"] != b["max"]:
            out.append({**base, "kind": "ranks", "from": a["max"], "to": b["max"]})
        if a.get("req") != b.get("req"):
            out.append({**base, "kind": "req", "from": a.get("req"), "to": b.get("req")})
        if a.get("cost") != b.get("cost") and a.get("cost") != "Active":
            c = {**base, "kind": "cost", "from": a.get("cost"), "to": b.get("cost")}
            if _cost_key(a.get("cost")) == _cost_key(b.get("cost")):
                c["minor"] = True
            out.append(c)
        if a.get("ranks") and b.get("ranks") and a["ranks"] != b["ranks"]:
            out.append({**base, "kind": "text", "from": a["ranks"][-1], "to": b["ranks"][-1]})
    def spell_map(d):
        return {(tab["name"], sp["name"]): sp for tab in (d.get("spells") or {}).get("tabs", []) for sp in tab["spells"]}
    so, sn = spell_map(old), spell_map(new)
    if so and sn:
        for key in sorted(sn.keys() - so.keys()):
            out.append({"kind": "spell_added", "tree": key[0], "name": key[1], "to": sn[key].get("levels")})
        for key in sorted(so.keys() - sn.keys()):
            out.append({"kind": "spell_removed", "tree": key[0], "name": key[1], "from": so[key].get("levels")})
        for key in sorted(sn.keys() & so.keys()):
            if so[key].get("levels") != sn[key].get("levels"):
                out.append({"kind": "spell_levels", "tree": key[0], "name": key[1],
                            "from": so[key].get("levels"), "to": sn[key].get("levels")})
    elif sn and not so:
        out.append({"kind": "spell_lists"})
    return out


def change_line(c):
    """One change as a line of the Markdown summary."""
    k, label = c["kind"], f"{c.get('tree')} / {c.get('name')}"
    f, t = c.get("from"), c.get("to")
    return {
        "new_class": lambda: "new class data",
        "spell_lists": lambda: "spell lists added",
        "added": lambda: f"added {label} (row {t['row']}, col {t['col']}, {t['max']} ranks)",
        "removed": lambda: f"removed {label}",
        "moved": lambda: f"moved {label}: row {f[0]} col {f[1]} -> row {t[0]} col {t[1]}",
        "ranks": lambda: f"max rank of {label}: {f} -> {t}",
        "req": lambda: f"prerequisite of {label}: {f or 'none'} -> {t or 'none'}",
        "cost": lambda: f"cost of {label}: {f or 'none'} -> {t or 'none'}" + (" (wording only)" if c.get("minor") else ""),
        "text": lambda: f"text changed: {label}",
        "spell_added": lambda: f"new spell {label} (levels {t or 'unknown'})",
        "spell_removed": lambda: f"spell removed: {label}",
        "spell_levels": lambda: f"learn levels of {label}: {f} -> {t}",
    }[k]()


def diff_class(old, new):
    """Human-readable list of talent changes, plus the set of talents whose text changed."""
    changes = diff_changes(old, new)
    changed_text = {(c["tree"], c["name"]) for c in changes if c["kind"] == "text"}
    return sorted(change_line(c) for c in changes), changed_text


# ---------------------------------------------------------------- update: stats

class _TableParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_stats_page(page):
    """Per-level table from a ForeverDB class page -> {table: [60 values]} or None."""
    p = _TableParser()
    p.feed(page)
    for table in p.tables:
        if not table or not table[0] or not table[0][0].lower().startswith("level"):
            continue
        cols = {}
        for i, head in enumerate(table[0]):
            h = head.lower()
            if "agility" in h and "crit" in h:
                cols[i] = "agi_per_crit"
            elif "intellect" in h and "crit" in h:
                cols[i] = "int_per_spell_crit"
            elif "mana" in h:
                cols[i] = "base_mana"
        out = {name: [None] * 60 for name in cols.values()}
        for row in table[1:]:
            m = re.match(r"\d+", row[0]) if row else None
            if not m or not 1 <= int(m.group(0)) <= 60:
                continue
            for i, name in cols.items():
                if i < len(row):
                    try:
                        out[name][int(m.group(0)) - 1] = float(row[i].replace(",", ""))
                    except ValueError:
                        pass
        if out and all(v is not None for vals in out.values() for v in vals):
            return out
    return None


# ---------------------------------------------------------------- update

def cmd_update(args):
    effects = load_effects()
    entry = {"date": args.date, "classes": {}, "changes": {}, "review": [], "builds": {}}
    failed = []
    for cls in args.classes:
        old = read_json(DATA / "talents" / f"{cls}.json")
        try:
            if args.from_dir:
                raw = (Path(args.from_dir) / f"{cls}.json").read_text(encoding="utf-8")
            else:
                raw = fetch(TALENT_SOURCE["export"].format(cls=cls))
            new = convert_export(cls, json.loads(raw), old, args.date)
            problems = validate_class(new)
            if problems:
                raise ValueError("; ".join(problems))
        except Exception as exc:  # keep the old data for this class and carry on
            failed.append(f"{cls}: {exc}")
            continue
        changes = diff_changes(old, new)
        lines = sorted(change_line(c) for c in changes if not c.get("minor"))
        minor = sum(1 for c in changes if c.get("minor"))
        if minor:
            lines.append(f"{minor} cost lines reworded with no change in substance")
        changed_text = {(c["tree"], c["name"]) for c in changes if c["kind"] == "text"}
        same_meta = old and old["source"].get("build") == new["source"]["build"] \
            and old["source"].get("generated") == new["source"]["generated"]
        first_export = old and old["source"].get("method", "").startswith("seed")
        if not lines and same_meta and not first_export:
            continue
        if lines:
            entry["classes"][cls] = lines
            entry["changes"][cls] = changes
        if old and old["source"].get("build") != new["source"]["build"]:
            entry["builds"][cls] = [old["source"].get("build"), new["source"]["build"]]
        entry["review"].extend(effects_review(cls, new, effects, changed_text))
        if not args.dry_run:
            write_json(DATA / "talents" / f"{cls}.json", new)

    stats_changed = []
    if args.stats:
        stats = read_json(DATA / "stats.json")
        for cls in args.classes:
            try:
                if args.from_dir:
                    page = (Path(args.from_dir) / f"{cls}.html").read_text(encoding="utf-8")
                else:
                    page = fetch(STATS_SOURCE["page"].format(cls=cls))
                tables = parse_stats_page(page)
                if tables is None:
                    raise ValueError("no complete level 1-60 table found on the page")
            except Exception as exc:
                failed.append(f"{cls} stats: {exc}")
                continue
            if stats["classes"].get(cls) != tables:
                stats["classes"][cls] = tables
                stats_changed.append(cls)
        if stats_changed and not args.dry_run:
            stats["source"]["retrieved"] = args.date
            write_json(DATA / "stats.json", stats)
            entry["classes"]["_stats"] = [f"per-level stat tables changed: {', '.join(stats_changed)}"]
            for cls in stats_changed:
                entry["changes"].setdefault(cls, []).append({"kind": "stats"})

    changed = bool(entry["classes"] or entry["builds"])
    md = ["# Game data update " + args.date, ""]
    if not changed:
        md.append("No talent or stat changes found.")
    for cls, (a, b) in entry["builds"].items():
        md.append(f"- {cls}: source build {a} -> {b}")
    for cls, lines in entry["classes"].items():
        md += ["", f"## {cls.lstrip('_')}"] + [f"- {l}" for l in lines]
    if entry["review"]:
        md += ["", "## Needs a human look (data/effects.txt)"] + [f"- {l}" for l in entry["review"]]
    if failed:
        md += ["", "## Not updated"] + [f"- {l}" for l in failed]
    summary = "\n".join(md) + "\n"
    print(summary)
    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")
    if changed and not args.dry_run:
        log = read_json(DATA / "changelog.json", [])
        log.insert(0, entry)
        write_json(DATA / "changelog.json", log)
    if not args.dry_run:
        cmd_build(args)
    if failed and len(failed) >= len(args.classes):
        return 1
    return 0


# ---------------------------------------------------------------- build / check

def updates_index(log, rules):
    """What the site needs up front: when the last update was and which talents it touched."""
    latest = log[0] if log else None
    touched = {}
    if latest:
        for cls, changes in (latest.get("changes") or {}).items():
            touched[cls] = sorted({f"{c['tree']}/{c['name']}" for c in changes
                                   if c.get("name") and not c.get("minor") and not c["kind"].startswith("spell")})
    return {"count": len(log), "latest": latest and latest["date"], "touched": touched,
            "official": rules.get("official_notes", [])}


def cmd_build(args):
    rules = read_json(DATA / "rules.json")
    stats = read_json(DATA / "stats.json")
    effects = load_effects()
    manifest = {"schema": SCHEMA, "built": args.date, "rules": rules["talents"],
                "conversions": rules["conversions"], "stats": rules["stats"], "classes": [],
                "sources": {"talents": {k: TALENT_SOURCE[k]
                                        for k in ("name", "url", "license", "license_url", "attribution", "changes")},
                            "stats": {"name": STATS_SOURCE["name"], "url": STATS_SOURCE["url"],
                                      "license": STATS_SOURCE["license"],
                                      "build": stats["source"].get("build"),
                                      "retrieved": stats["source"].get("retrieved")},
                            "icons": {"name": "Blizzard Entertainment", "host": "Wowhead (wow.zamimg.com)"},
                            "credits": rules.get("project", {}).get("credits")},
                "updates": updates_index(read_json(DATA / "changelog.json", []), rules)}
    problems, review = [], []
    for cls in CLASSES:
        doc = read_json(DATA / "talents" / f"{cls}.json")
        problems += validate_class(doc)
        review += effects_review(cls, doc, effects)
        meta = rules["classes"][cls]
        for tree in doc["trees"]:
            for t in tree["talents"]:
                effs = [e for e in effects[cls].get((tree["name"], t["name"]), []) if len(e["values"]) == t["max"]]
                if effs:
                    t["effects"] = effs
        talent_names = {t["name"] for tree in doc["trees"] for t in tree["talents"]}
        for tab in (doc.get("spells") or {}).get("tabs", []):
            for sp in tab["spells"]:
                if sp["name"] in talent_names:
                    sp["talent"] = True
        doc.setdefault("spells", {"tabs": [], "general": []})
        doc["source"].update({k: TALENT_SOURCE[k] for k in ("license_url", "attribution", "changes")})
        doc.update({"name": meta["name"], "color": meta["color"],
                    "consts": {k: meta[k] for k in ("ap_per_str", "ap_per_agi", "rap_per_agi", "block_value")},
                    "tables": stats["classes"].get(cls, {})})
        write_json(SITE_DATA / f"{cls}.json", doc, compact=True)
        manifest["classes"].append({"key": cls, "name": meta["name"], "color": meta["color"],
                                    "build": doc["source"].get("build"), "generated": doc["source"].get("generated"),
                                    "method": doc["source"].get("method")})
    if problems:
        raise SystemExit("data problems:\n" + "\n".join(problems))
    # Icons: use the copies in site/icons/ when every one is there, else the remote host.
    icons = rules.get("icons", {})
    names = icon_names()
    local_dir = ROOT / "site" / icons.get("local_dir", "icons")
    have_all = bool(names) and all((local_dir / f"{n}.jpg").exists() for n in names)
    manifest["icons"] = {"url": (icons.get("local_dir", "icons") + "/{name}.jpg") if have_all else icons.get("remote"),
                         "local": have_all}
    write_json(SITE_DATA / "manifest.json", manifest, compact=True)
    write_json(SITE_DATA / "changelog.json", read_json(DATA / "changelog.json", []), compact=True)
    for line in review:
        print("review:", line)
    print(f"built site/data for {len(CLASSES)} classes")
    return 0


def icon_names():
    names = set()
    for cls in CLASSES:
        doc = read_json(DATA / "talents" / f"{cls}.json")
        names.update(t.get("icon") for tree in doc["trees"] for t in tree["talents"])
        names.update(sp.get("icon") for tab in (doc.get("spells") or {}).get("tabs", []) for sp in tab["spells"])
    names.discard(None)
    return sorted(n for n in names if re.fullmatch(r"[a-z0-9_]+", n))


def cmd_icons(args):
    """Download every icon the data refers to into site/icons/, so the site serves its own copies."""
    icons = read_json(DATA / "rules.json").get("icons", {})
    out = ROOT / "site" / icons.get("local_dir", "icons")
    out.mkdir(parents=True, exist_ok=True)
    names, got, missing = icon_names(), 0, []
    for name in names:
        target = out / f"{name}.jpg"
        if target.exists() and not args.force:
            continue
        try:
            req = urllib.request.Request(icons["remote"].format(name=name), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                target.write_bytes(resp.read())
            got += 1
        except Exception as exc:
            missing.append(f"{name}: {exc}")
    print(f"{len(names)} icons referenced, {got} downloaded, {len(missing)} failed")
    for line in missing[:20]:
        print("  missing", line)
    return cmd_build(args)


def cmd_check(args):
    effects = load_effects()
    problems, review = [], []
    for cls in CLASSES:
        doc = read_json(DATA / "talents" / f"{cls}.json")
        problems += validate_class(doc)
        # A stale curated effect is a note for whoever reviews the update, not an error:
        # build leaves out any effect that no longer matches its talent.
        review += effects_review(cls, doc, effects)
    stats = read_json(DATA / "stats.json")
    for cls, tables in stats["classes"].items():
        for name, vals in tables.items():
            if len(vals) != 60:
                problems.append(f"stats {cls}.{name}: {len(vals)} values")
    for line in review:
        print("review:", line)
    print("\n".join(problems) if problems else "data ok")
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=today(), help="date stamp to record (default: today)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    sub.add_parser("build")
    sub.add_parser("check")
    ic = sub.add_parser("icons")
    ic.add_argument("--force", action="store_true", help="download again even if the file exists")
    up = sub.add_parser("update")
    up.add_argument("--classes", nargs="+", default=CLASSES, choices=CLASSES)
    up.add_argument("--stats", action="store_true", help="also refresh the per-level stat tables (ForeverDB)")
    up.add_argument("--from-dir", help="read <class>.json / <class>.html from this folder instead of the network")
    up.add_argument("--dry-run", action="store_true", help="report changes without writing")
    up.add_argument("--summary-file", help="write the Markdown change summary here")
    args = ap.parse_args()
    return {"seed": cmd_seed, "build": cmd_build, "check": cmd_check, "update": cmd_update, "icons": cmd_icons}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
