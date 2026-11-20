"""Render the report's design diagrams (Mermaid) to PNG.

    python report/make_figures.py

Needs Playwright (pip install playwright && playwright install chromium) and
an internet connection the first time (Mermaid is loaded from a CDN).
Sources: report/diagrams/*.mmd  ->  output: report/figures/<name>.png
"""

import html
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "diagrams"
OUT = HERE / "figures"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;padding:24px;background:#fff;font-family:Arial,sans-serif}</style></head>
<body><pre class="mermaid">%s</pre>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs';
mermaid.initialize({startOnLoad:false, theme:'neutral', fontFamily:'Arial',
  flowchart:{htmlLabels:true, curve:'basis'}, themeVariables:{fontSize:'18px'}});
await mermaid.run();
document.body.dataset.done = '1';
</script></body></html>"""


def main(names: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    files = sorted(SRC.glob("*.mmd"))
    if names:
        files = [f for f in files if f.stem in names]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2, viewport={"width": 1600, "height": 1000})
        for f in files:
            page.set_content(PAGE % html.escape(f.read_text()))
            page.wait_for_selector("body[data-done]", timeout=30000)
            if page.query_selector(".error-icon"):
                raise SystemExit(f"{f.name}: Mermaid syntax error")
            page.locator("pre.mermaid svg").screenshot(path=str(OUT / f"{f.stem}.png"))
            print("wrote", OUT / f"{f.stem}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
