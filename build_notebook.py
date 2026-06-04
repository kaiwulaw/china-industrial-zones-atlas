#!/usr/bin/env python3
"""Generate China_Industrial_Zones_Atlas.ipynb from app.py.

The notebook is the same code as app.py, split into cells by section, with
markdown headers and a Jupyter-native run cell (app.run(jupyter_mode=...)).
Regenerate any time app.py changes:  python build_notebook.py
"""
import re
import nbformat as nbf

src = open("app.py", encoding="utf-8").read()

# Strip the module docstring (becomes the intro markdown) and the __main__ block.
m = re.search(r'"""(.*?)"""', src, re.S)
doc = m.group(1).strip()
src_body = src[m.end():].lstrip("\n")
src_body = re.split(r'\nif __name__ == "__main__":', src_body)[0].rstrip() + "\n"

# Split the body on the section banners.
banner = re.compile(r'# ={60}\n# (.+?)\n# ={60}\n')
parts = banner.split(src_body)
head = parts[0].strip("\n")                       # imports (before first banner)
sections = list(zip(parts[1::2], parts[2::2]))    # (title, code) pairs

# Short markdown blurbs keyed by the first word(s) of each banner title.
BLURBS = {
    "DESIGN": "Palette, fonts, the shared Plotly template, and the map base style "
              "— one editorial *cartographic atlas* look applied everywhere.",
    "DATA": "Load and prepare the zone-level (`enriched.csv`) and county-level "
            "(`analysis_units.csv`) frames: parse approval years, map Chinese "
            "labels to English, derive cohorts and pre/post built-up, and "
            "precompute the non-zone urbanization baseline.",
    "STATISTICS": "Pure helpers: Cohen's *d* (standardized mean difference), the "
                  "effect-size labeller, and the zone-vs-non-zone comparison table.",
    "TAB 1": "**Placement Explorer** figures — zone map, selection-vs-national "
             "distribution, and the approvals timeline. All pure functions.",
    "TAB 2": "**Zone vs Non-Zone Comparator** figures — county map, the live SMD "
             "effect chart (standardized zone vs non-zone comparison), and "
             "group distributions.",
    "TAB 3": "**Designation Event Study** figures — built-up area aligned to each "
             "zone's approval year (τ = 0), the selection check against the "
             "non-zone baseline, and the pre/post scatter.",
    "LAYOUT": "Masthead, the three tabs, the per-tab control panels, and the "
              "colophon. `assets/style.css` is loaded automatically.",
    "CALLBACKS": "One render callback to switch tabs, plus one update callback per "
                 "tab wiring the Dash Core Components to the figures.",
}

cells = []
md = cells.append

md(nbf.v4.new_markdown_cell(
    "# China's Industrial Development Zones — An Interactive Atlas\n"
    "### COMP 4433 · Project 2 · Kai Wu\n\n" + doc +
    "\n\n---\n**To launch:** run every cell top to bottom; the final cell renders "
    "the app inline. If the inline frame is cramped, change `jupyter_mode` to "
    "`\"external\"` (prints a localhost link) or `\"tab\"` (opens a browser tab)."))

md(nbf.v4.new_markdown_cell("## Imports"))
cells.append(nbf.v4.new_code_cell(head))

for title, code in sections:
    key = title.split("  ")[0].split(" —")[0].strip()
    blurb = next((v for k, v in BLURBS.items() if key.startswith(k)), "")
    clean = title.split("  ")[0].split(" —")[0].strip().title()
    md(nbf.v4.new_markdown_cell(f"## {clean}\n\n{blurb}"))
    cells.append(nbf.v4.new_code_cell(code.strip("\n")))

md(nbf.v4.new_markdown_cell(
    "## Run the app\n\n"
    "Renders inline below. The same `app` object is what `app.py` serves, so "
    "behaviour is identical to `python app.py`."))
cells.append(nbf.v4.new_code_cell(
    '# jupyter_mode: "inline" (in-notebook) | "external" (localhost link) | "tab"\n'
    'app.run(jupyter_mode="inline", port=8050)'))

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata.update({
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
})
nbf.write(nb, "China_Industrial_Zones_Atlas.ipynb")
print(f"Wrote China_Industrial_Zones_Atlas.ipynb with {len(cells)} cells "
      f"({len(sections)} code sections).")
