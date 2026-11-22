# Credits

This planner stands on other people's work. Everything it uses that was not
written for this project is listed here with its source and terms.

## What the project's license covers

The [CC0 1.0](LICENSE) dedication covers the code and text written for this
project by its author: the C engine, the site's HTML, CSS and JavaScript, the
tools, the tests and the documentation. It does **not** cover the third-party
material below, which stays under its own terms. If you reuse this project,
keep these credits.

## Game data

### Talents Forever
<https://talentsforever.com/> · licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

> Talent data from Talents Forever (https://talentsforever.com/), licensed
> CC BY 4.0.

Used for: every class's talent trees (talent names, positions, ranks,
prerequisites and costs), talent rank text, icon names, and the trainer skill
lists with the level each rank is learned.

Changes made here: reformatted into this project's JSON files
(`data/talents/*.json`, `site/data/*.json`); until the first data update the
talent descriptions are short summaries written from the original text; stat
effects in `data/effects.txt` are read off the talent text by hand; the app
computes per-rank and per-level values from the text. The updater
(`tools/wfdata.py update`) records further changes in `data/changelog.json`.

### ForeverDB
<https://foreverdb.net/stats>

Used for: the per-level class tables (Agility per 1% crit, Intellect per 1%
spell crit, base mana) and the stat conversion figures (health per Stamina,
mana per Intellect, armor per Agility, attack power per Strength and Agility,
rating per 1%, block value per Strength). ForeverDB states no license for
these pages; the numbers are credited here and in the app.

## Images

### Icons
Talent and skill icons are World of Warcraft artwork by Blizzard
Entertainment. By default the app loads them from Wowhead's icon host
(`wow.zamimg.com`); the address is set in `data/rules.json` under
`icons.remote`.

### Fonts
- [Cinzel](https://fonts.google.com/specimen/Cinzel) by Natanael Gama, SIL
  Open Font License 1.1
- [Source Sans 3](https://fonts.google.com/specimen/Source+Sans+3) by Paul D.
  Hunt for Adobe, SIL Open Font License 1.1

Both are served by Google Fonts.

## World of Warcraft

World of Warcraft, World of Warcraft: Forever, and the game's class, talent
and spell names, tooltip text and icons are trademarks or copyrighted material
of Blizzard Entertainment, Inc. This is an unofficial fan tool and is not
affiliated with or endorsed by Blizzard Entertainment.

## Tools

Built with [LLVM/Clang](https://llvm.org/) (WebAssembly engine),
[Python](https://www.python.org/) (data pipeline) and
[Node.js](https://nodejs.org/) (tests). Deployed with GitHub Actions and
GitHub Pages.

The code was written with [Claude](https://claude.com/) (Anthropic).
