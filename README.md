# wowfe_talent_planner-ai

Tool to calculate different class talent configurations in WoW Forever.
A talent planner for World of Warcraft: Forever. Pick a class, spend points
across its three trees, and see

- **Bonuses**: every talent you took at its current rank, with stat boosts
  added up across trees;
- **Skills**: every skill the class trainer teaches and the level of each
  rank, listed by level or by tree, following the level slider;
- **Base stats**: class numbers at any level (the level slider drives both the
  talent point budget and this panel), plus what your own attributes turn into
  once talents are applied.

It is a static site: a rules engine written in C and compiled to WebAssembly,
a thin JavaScript UI, and JSON data files. It deploys to GitHub Pages as is.

## Run it

```
make serve          # http://localhost:8000
make test           # engine, data and updater tests
make single         # dist/wowfe_talent_planner.html, one file, works offline
```

`make serve` only needs Python 3. Rebuilding the engine needs `clang` with the
wasm linker (`lld`); the compiled `site/planner.wasm` is committed, so you can
skip that unless you change `core/`.

## Layout

| Path | What it is |
| --- | --- |
| `core/planner.c`, `planner.h` | Rules engine: rows, prerequisites, point budget, build strings, stat maths. Freestanding C99. |
| `site/` | What gets published: `index.html`, `style.css`, `app.js`, `planner.wasm`, `data/`. |
| `data/talents/*.json` | Canonical talent data, icon names and skill lists, one file per class. |
| `data/stats.json` | Per-level class tables (crit conversions, base mana). |
| `data/rules.json` | Game rules, conversions, class constants, stat definitions. |
| `data/effects.txt` | Hand-curated stat effects (which talent gives +5% parry, and so on). |
| `data/changelog.json` | Written by the updater; shown in the app. |
| `tools/wfdata.py` | Data pipeline: `update`, `build`, `check`, `seed`. |
| `tests/` | Native engine tests, wasm tests against every class, updater tests. |

Nothing about a class or a rule is hard-coded in the engine or the UI. To
change the game, change `data/` and run `make data`.

## Updating after a game patch

```
make update         # python3 tools/wfdata.py update --stats
```

This pulls the current talent export for each class from Talents Forever and
the per-level tables from ForeverDB, then:

1. rewrites `data/talents/*.json` and `data/stats.json` where something changed;
2. prints a summary of what moved, was added or removed, changed rank count,
   prerequisite or text, and records it in `data/changelog.json`;
3. lists any entry in `data/effects.txt` that now points at a changed or
   missing talent, because those are curated by hand and need a look;
4. rebuilds `site/data/`.

Useful flags: `--dry-run` (report only), `--classes mage priest`,
`--from-dir downloads/` (read `<class>.json` and `<class>.html` you saved by
hand, for when a source blocks scripted requests).

Saved builds are stored by talent name, so they carry over an update; points
that no longer fit are reported when the build is loaded. Share links are
positional and can break when a tree is rearranged.

`.github/workflows/update-data.yml` runs the same command daily and opens a
pull request when anything changed.

## Icons

Talents and skills carry the game's icon names (for example `ability_parry`).
The site turns a name into an image URL with the pattern in
`data/rules.json` under `icons.remote`, which points at Wowhead's icon host by
default. An icon that fails to load is dropped and the name is shown instead,
so the planner works without them.

To serve the images from your own site instead of someone else's host:

```
python3 tools/wfdata.py icons     # downloads into site/icons/ and rebuilds
```

Once every icon is in `site/icons/`, the build switches to the local copies.
The images are Blizzard's artwork, so whether to commit them to a public
repository is your call. The default URL pattern was not tested from the
machine this was written on; if icons do not appear, check `icons.remote`.

## Deploying to GitHub Pages

1. Push this repository to GitHub.
2. Settings -> Pages -> Source: **GitHub Actions**.
3. Push to `main`. `.github/workflows/pages.yml` builds, tests and publishes `site/`.

For the scheduled data update to open pull requests, also allow Actions to
create pull requests under Settings -> Actions -> General.

## State of the data

- Talent layouts (name, position, ranks, prerequisites) for all nine classes
  were read from the Talents Forever export of client build 1.60.1.70755. The
  descriptions are short summaries. The first `make update` replaces them with
  the full text of every rank.
- Skill lists and learn levels come from the same export. Four skills have no
  level in it and are listed as such: Paladin *Sense Undead*, Mage *Polymorph
  (Turtle)* and *(Pig)*, Warlock pet *Lesser Invisibility*.
- Two positions were ambiguous in what was read and were resolved by hand:
  Warrior Fury *Enrage* (placed at row 3, column 4) and Mage Fire *Impact*
  (placed at row 2, column 3). The first update settles both.
- The updater's export parser was written from a description of the export
  format and is tested against a mock in that shape (`tests/test_update.py`),
  not yet against the live files.
- Two rules are carried over from Classic and marked `assumed` in
  `data/rules.json`: 5 points per row to unlock the next, and prerequisites
  need max rank.
- The game client does not expose base Strength, Agility, Stamina, Intellect,
  Spirit or base health per level, so the Base stats panel shows what is
  known (crit conversions, base mana, talent points) and takes your attributes
  as input.

## Credits

Talent data from [Talents Forever](https://talentsforever.com/), licensed
CC BY 4.0. Per-level stat tables from [ForeverDB](https://foreverdb.net/stats).
Game names and tooltip text belong to Blizzard Entertainment. This project is
not affiliated with Blizzard.
