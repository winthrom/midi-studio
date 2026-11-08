#!/usr/bin/env python3
"""Builds docs/MIDI-Studio-User-Guide.pdf from docs/USER_GUIDE.md.

Run from the repository root:   python3 docs/dev/build_user_guide.py

Needs:  pandoc (https://pandoc.org), and Python's playwright with its Chromium (pip install playwright;
        playwright install chromium), plus the DejaVu Sans fonts.
The page jumps used by Help > Where do I find... are the headings' ids, made by pandoc from the heading
text ("## Fingering Numbers" becomes #fingering-numbers).  If you rename a heading, change its entries in
gui.py (_where_dialog) and in the Index at the end of USER_GUIDE.md.
"""
import os, subprocess, sys, tempfile

CSS = """
@page { size: letter; margin: 0.75in 0.8in; }
body { font-family: "DejaVu Sans", sans-serif; font-size: 9.6pt; line-height: 1.45; color:#1f2328; max-width: none; }
header#title-block-header { margin-bottom: 1.2em; }
h1.title { font-size: 22pt; margin: 0 0 .1em; color:#12315c; border: none; }
p.subtitle { font-size: 12pt; color:#57606a; margin: 0 0 .6em; }
h1 { font-size: 15pt; color:#12315c; border-bottom: 1.5px solid #12315c; padding-bottom: 3px; margin-top: 1.6em; break-after: avoid; }
h2 { font-size: 12pt; color:#1b4f8a; margin-top: 1.3em; break-after: avoid; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.6pt; background:#f3f4f6; padding: 0 2px; }
table { border-collapse: collapse; margin: .6em 0; width: 100%; break-inside: avoid; }
th, td { border: 1px solid #c9d1d9; padding: 4px 7px; vertical-align: top; text-align: left; }
th { background:#eef2f7; }
a { color:#0b5cad; text-decoration: none; }
ul, ol { padding-left: 1.4em; }
li { margin: .15em 0; }
hr { border: none; border-top: 1px solid #c9d1d9; margin: 1.5em 0 .6em; }
"""
FOOTER = ('<div style="font-size:8px;width:100%;text-align:center;color:#57606a;font-family:DejaVu Sans">'
          'MIDI Studio User Guide &nbsp;&middot;&nbsp; page <span class="pageNumber"></span> of '
          '<span class="totalPages"></span></div>')

def main():
    root = os.getcwd()
    src = os.path.join(root, "docs", "USER_GUIDE.md")
    out = os.path.join(root, "docs", "MIDI-Studio-User-Guide.pdf")
    if not os.path.isfile(src):
        sys.exit("Run this from the repository root (docs/USER_GUIDE.md not found).")
    with tempfile.TemporaryDirectory() as tmp:
        css = os.path.join(tmp, "guide.css"); html = os.path.join(tmp, "guide.html")
        open(css, "w").write(CSS)
        subprocess.run(["pandoc", "-f", "markdown", "-t", "html5", "-s", "--metadata", "pagetitle=MIDI Studio User Guide",
                        "-c", css, "--embed-resources", src, "-o", html], check=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(); pg.goto("file://" + html); pg.wait_for_timeout(500)
            pg.pdf(path=out, format="Letter", print_background=True, prefer_css_page_size=True, tagged=True,
                   outline=True, display_header_footer=True, header_template="<span></span>", footer_template=FOOTER,
                   margin={"top": "0.75in", "bottom": "0.8in", "left": "0.8in", "right": "0.8in"})
            b.close()
    print("Wrote", out)

main()
