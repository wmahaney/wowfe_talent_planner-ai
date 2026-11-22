#!/usr/bin/env python3
"""Offline test of the data updater: feed it a made-up export in the upstream
shape and check that it converts and reports the differences. Writes nothing."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import wfdata  # noqa: E402


def fake_export(doc):
    """Our class document re-expressed in the Talents Forever export shape."""
    trees = []
    for tree in doc["trees"]:
        talents = []
        for t in tree["talents"]:
            item = {"name": t["name"], "max": t["max"], "row": t["row"], "col": t["col"],
                    "passive": not t["cost"], "icon": "x",
                    "desc": [f"{t['name']} rank {r + 1} text." for r in range(t["max"])]}
            if t["req"]:
                item["req"] = t["req"]
            if t["cost"] and t["cost"] != "Active":
                item["cost"] = t["cost"]
            talents.append(item)
        trees.append({"name": tree["name"], "bg": 1, "icon": "x", "talents": talents, "removed": []})
    book = {"general": [["Attack", ""], ["Dodge", "Passive"]],
            "tabs": [{"name": "Arms", "spells": [["Charge", "Rank 3"], ["Charge", "Rank 2"], ["Retaliation", ""]]}],
            "levels": {"Charge": [4, 26, 46]}, "icons": {"Charge": "ability_warrior_charge"}}
    desc = {"Warrior|Retaliation|": {"lv": "Learned at level 20", "d": "x"},
            "Warrior|Charge|Rank 2": {"lv": "Learned at level 26", "d": "x"}}
    return {"_readme": "Talent data from the WoW Forever client, build 1.60.1.99999.", "generated": "2027-01-05",
            "class": doc["class"], "talents": {"trees": trees}, "spellbook": book, "spell_desc": desc}


def main():
    old = wfdata.read_json(wfdata.DATA / "talents" / "warrior.json")
    export = fake_export(old)

    # First import after the seed: same shape, text arrives, nothing structural changes.
    first = wfdata.convert_export("warrior", copy.deepcopy(export), old, "2027-01-06")
    assert wfdata.validate_class(first) == []
    assert first["source"]["build"] == "1.60.1.99999" and first["source"]["generated"] == "2027-01-05"
    assert first["trees"][0]["talents"][0]["ranks"][0].endswith("rank 1 text.")
    assert first["trees"][0]["talents"][0]["summary"], "summary kept while the text is unverified"
    assert first["trees"][0]["talents"][0]["icon"] == "x", "icon comes from the export"
    arms_spells = first["spells"]["tabs"][0]["spells"]
    assert arms_spells == [{"name": "Charge", "levels": [4, 26, 46], "icon": "ability_warrior_charge"},
                           {"name": "Retaliation", "levels": [20], "icon": None}], arms_spells
    assert first["spells"]["general"][1] == {"name": "Dodge", "note": "Passive"}
    lines, changed = wfdata.diff_class(old, first)
    assert not changed and all("spell" in l or "learn levels" in l for l in lines), lines
    first["spells"] = old["spells"]

    # A patch: one talent gains a rank, one is reworded, one is replaced, one moves.
    arms = export["talents"]["trees"][0]["talents"]
    by_name = {t["name"]: t for t in arms}
    by_name["Deflection"]["max"] = 3
    by_name["Deflection"]["desc"] = ["a", "b", "c"]
    by_name["Improved Rend"]["desc"][0] = "Reworded."
    by_name["Improved Charge"]["name"] = "Juggernaut"
    by_name["Improved Hamstring"]["col"] = 4
    export["spellbook"] = {"general": [], "levels": {"Charge": [4, 24, 46]}, "icons": {},
                           "tabs": [{"name": t["name"], "spells": [[s["name"], ""] for s in t["spells"]]}
                                    for t in old["spells"]["tabs"]]}
    export["spell_desc"] = {f"Warrior|{s['name']}|": {"lv": f"Learned at level {s['levels'][0]}"}
                            for t in old["spells"]["tabs"] for s in t["spells"] if s["levels"] and len(s["levels"]) == 1}
    export["spellbook"]["levels"].update({s["name"]: s["levels"] for t in old["spells"]["tabs"] for s in t["spells"]
                                          if s["levels"] and len(s["levels"]) > 1 and s["name"] != "Charge"})
    second = wfdata.convert_export("warrior", export, first, "2027-02-01")
    lines, changed = wfdata.diff_class(first, second)
    text = "\n".join(lines)
    assert "max rank of Arms / Deflection: 5 -> 3" in text, text
    assert "text changed: Arms / Improved Rend" in text, text
    assert "added Arms / Juggernaut" in text and "removed Arms / Improved Charge" in text, text
    assert "moved Arms / Improved Hamstring" in text, text
    assert ("Arms", "Improved Rend") in changed
    assert "learn levels of Arms / Charge: [4, 26, 46] -> [4, 24, 46]" in text, text
    assert "spell removed" not in text and "new spell" not in text, text
    deflection = next(t for t in second["trees"][0]["talents"] if t["name"] == "Deflection")
    assert deflection["summary"] is None, "stale summary dropped when the talent changes"

    # The curated parry effect has 5 values but the talent now has 3 ranks.
    review = wfdata.effects_review("warrior", second, wfdata.load_effects(), changed)
    assert any("Deflection" in r for r in review), review

    # Stats page scraping.
    rows = "".join(f"<tr><td>{l}{' (level cap)' if l == 60 else ''}</td><td>{l / 2:.1f}</td><td>{l}.5</td>"
                   f"<td>{1000 + l:,}</td></tr>" for l in range(1, 61))
    page = ("<table><tr><th>Level</th><th>Agility for 1% crit</th><th>Intellect for 1% spell crit</th>"
            f"<th>Base mana</th></tr>{rows}</table>")
    tables = wfdata.parse_stats_page(page)
    assert tables["base_mana"][59] == 1060 and tables["agi_per_crit"][0] == 0.5 and len(tables["int_per_spell_crit"]) == 60
    assert wfdata.parse_stats_page("<table><tr><th>Level</th></tr></table>") is None

    print("updater tests passed")


if __name__ == "__main__":
    main()
