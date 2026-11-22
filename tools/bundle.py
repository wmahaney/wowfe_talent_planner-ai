#!/usr/bin/env python3
"""Pack the site into one HTML file (dist/wowfe_talent_planner.html).

The result needs no server and no other files: data and the WebAssembly engine
are embedded. Handy for sending the planner to someone or opening it offline.
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def main():
    page = (SITE / "index.html").read_text(encoding="utf-8")
    data = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((SITE / "data").glob("*.json"))}
    inline = {"data": data, "wasm": base64.b64encode((SITE / "planner.wasm").read_bytes()).decode("ascii")}
    blob = json.dumps(inline, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    css = (SITE / "style.css").read_text(encoding="utf-8")
    js = (SITE / "app.js").read_text(encoding="utf-8")
    link, script = '<link rel="stylesheet" href="style.css">', '<script src="app.js"></script>'
    assert link in page and script in page, "index.html no longer has the expected style/script tags"
    page = page.replace(link, f"<style>\n{css}</style>")
    page = page.replace(script, f"<script>window.WF_INLINE={blob};</script>\n<script>\n{js}</script>")
    out = ROOT / "dist" / "wowfe_talent_planner.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
