"""Render README.md into a styled, shareable A4 PDF via headless Chromium.

Usage:  python tools/build_readme_pdf.py README.md InvestSync-Research-Tools.pdf
Needs:  pip install markdown playwright && playwright install chromium
"""
import base64
import re
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

README = Path(sys.argv[1])
OUT = Path(sys.argv[2])
LOGOS = Path(__file__).resolve().parent.parent / "investsync" / "render" / "assets"

src = README.read_text(encoding="utf-8")

# 1. Drop the GitHub <picture> logo block; we build our own header.
src = re.sub(r'^<p align="center">.*?</p>\s*', "", src, flags=re.S)

# 2. Replace the two LaTeX snippets with plain typography.
src = src.replace(
    r"($\text{ROE} = \text{Net Margin} \times \text{Asset Turnover} \times \text{Leverage}$)",
    "(<em>ROE = Net Margin × Asset Turnover × Leverage</em>)",
)
src = src.replace(r"$<300\text{ ms}$", "&lt;300 ms")

# 2b. README diagram row is 1 char short; pad so the right border lines up.
src = src.replace("(`#1B3A8C`, fonts)   │", "(`#1B3A8C`, fonts)    │")

# 3. Strip decorative emoji from headings.
src = re.sub(r"^(#+)\s*[^\w\s#]+️?\s+", r"\1 ", src, flags=re.M)

# 4. Python-Markdown needs 4-space nesting; README uses 2.
src = re.sub(r"^( {1,6})(- )",
             lambda m: (" " * 4 if len(m.group(1)) <= 3 else " " * 8) + m.group(2),
             src, flags=re.M)

# 4b. GitHub lets a list follow a paragraph line directly; Python-Markdown needs a blank line.
src = re.sub(r"^((?![ \t]*(?:[-*]|\d+\.) )[^\n|`].*)\n([ \t]*- )", r"\1\n\n\2", src, flags=re.M)

# 5. Pull out the title + tagline so the header can be laid out by hand.
title_m = re.search(r"^# (.+)$", src, flags=re.M)
title = title_m.group(1)
src = src.replace(title_m.group(0), "", 1)

body = markdown.markdown(src, extensions=["tables", "fenced_code", "sane_lists"])

# Task-list checkboxes.
body = body.replace("<li>[x] ", '<li class="task done"><span class="box">✓</span>')
body = body.replace("<li>[ ] ", '<li class="task"><span class="box"></span>')
body = body.replace("<li><p>[x] ", '<li class="task done"><p><span class="box">✓</span>')
body = body.replace("<li><p>[ ] ", '<li class="task"><p><span class="box"></span>')

# Lay the two workstreams side by side as cards.
ws = re.search(r"(<h3>Workstream A.*?)(<h3>Workstream B.*?)(?=<h3>Working Agreement)", body, re.S)
if ws:
    body = body.replace(ws.group(0),
        f'<div class="split"><div class="card">{ws.group(1)}</div>'
        f'<div class="card">{ws.group(2)}</div></div>')

# Framework Deep Dive: own page, provides/use side by side.
body = body.replace("<h2>Framework Deep Dive</h2>", '<h2 class="new-page">Framework Deep Dive</h2>')
body = re.sub(
    r"<p><strong>What it provides</strong></p>\s*(<ul>.*?</ul>)\s*"
    r"<p><strong>What we use</strong></p>\s*(<ul>.*?</ul>)",
    r'<div class="fw-cols"><div><div class="fw-label">What it provides</div>\1</div>'
    r'<div class="fw-use"><div class="fw-label">What we use</div>\2</div></div>',
    body, flags=re.S)
dd = re.search(r'(<h2 class="new-page">Framework Deep Dive</h2>)(.*?)(?=<h2>)', body, re.S)
if dd:
    inner = re.sub(r"(<h3>.*?)(?=<h3>|$)", r'<div class="fw">\1</div>', dd.group(2), flags=re.S)
    body = body.replace(dd.group(0), dd.group(1) + '<div class="deep-dive">' + inner + "</div>")

# Wrap the subtitle block (first two paragraphs) for header styling.
body = body.replace("<hr />", "", 1)


def logo(name):
    data = base64.b64encode((LOGOS / f"{name}.png").read_bytes()).decode()
    return f"data:image/png;base64,{data}"


title_main, _, title_sub = title.partition(":")

html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --navy: #1B3A8C;
    --ink: #1d2433;
    --muted: #5b6475;
    --rule: #d9dee8;
    --tint: #f3f5fa;
  }}
  @page {{ size: A4; margin: 18mm 17mm 20mm 17mm; }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{
    margin: 0;
    font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", sans-serif;
    font-size: 10pt; line-height: 1.5; color: var(--ink);
  }}

  .logos {{ display: flex; align-items: center; justify-content: space-between;
           padding-bottom: 10pt; border-bottom: 2.5pt solid var(--navy); }}
  .logos img {{ height: 34pt; }}
  .logos img.cuhk {{ height: 28pt; }}
  .eyebrow {{ margin: 16pt 0 2pt; font-size: 8.5pt; font-weight: 700;
             letter-spacing: .12em; text-transform: uppercase; color: var(--navy); }}
  h1 {{ margin: 0; font-size: 24pt; line-height: 1.15; color: var(--navy); letter-spacing: -.01em; }}
  h1 small {{ display: block; margin-top: 4pt; font-size: 14pt; font-weight: 400; color: var(--ink); }}

  /* the two intro lines (project tag + tagline) */
  .content > p:first-child {{ margin: 10pt 0 2pt; color: var(--muted); font-size: 9.5pt; }}
  .content > p:first-child strong {{ color: var(--ink); }}
  .content > p:nth-child(2) {{ margin-top: 0; }}

  h2 {{ margin: 22pt 0 8pt; padding-bottom: 4pt; font-size: 14pt; color: var(--navy);
        border-bottom: 1pt solid var(--rule); break-after: avoid; }}
  h3 {{ margin: 14pt 0 4pt; font-size: 11pt; color: var(--ink); break-after: avoid; }}
  p {{ margin: 0 0 7pt; }}
  hr {{ display: none; }}
  a {{ color: var(--navy); text-decoration: none; border-bottom: .5pt solid #9fb0d8; }}
  strong {{ font-weight: 700; }}

  ul, ol {{ margin: 0 0 8pt; padding-left: 16pt; }}
  li {{ margin: 2pt 0; }}
  li > ul {{ margin: 2pt 0 4pt; }}
  .content > ol > li {{ break-inside: avoid; }}
  li.task {{ list-style: none; margin-left: -16pt; break-inside: avoid; }}
  li.task > ul {{ padding-left: 32pt; }}
  .box {{ display: inline-block; width: 9pt; height: 9pt; margin-right: 6pt;
          border: 1pt solid #8892a6; border-radius: 2pt; vertical-align: -1pt;
          font-size: 7pt; line-height: 8pt; text-align: center; color: #fff; }}
  li.done > .box, li.done > p > .box {{ background: var(--navy); border-color: var(--navy); }}

  .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; margin: 8pt 0 6pt;
            break-inside: avoid; }}
  .card {{ border: .75pt solid var(--rule); border-top: 3pt solid var(--navy); border-radius: 4pt;
           padding: 9pt 11pt 4pt; font-size: 9pt; line-height: 1.45; }}
  .card h3 {{ margin: 0 0 1pt; font-size: 10.5pt; color: var(--navy); }}
  .card p {{ margin-bottom: 6pt; color: var(--muted); font-size: 8.5pt; }}
  .card ul {{ padding-left: 12pt; }}
  .card li {{ margin: 2.5pt 0; }}
  .card code {{ font-size: 7.8pt; }}

  h2.new-page {{ break-before: page; margin-top: 0; }}
  .deep-dive {{ font-size: 8.5pt; line-height: 1.36; }}
  .fw {{ break-inside: avoid; }}
  .deep-dive > p:first-child {{ font-size: 9.5pt; margin-bottom: 4pt; }}
  .deep-dive h3 {{ margin: 10pt 0 1pt; font-size: 10.5pt; color: var(--navy); }}
  .deep-dive h3 + p {{ margin-bottom: 5pt; color: var(--muted); }}
  .deep-dive code {{ font-size: 7.6pt; }}
  .fw-cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8pt; break-inside: avoid; }}
  .fw-cols > div {{ border: .75pt solid var(--rule); border-radius: 4pt; padding: 6pt 9pt 2pt; }}
  .fw-cols .fw-use {{ background: var(--tint); border-color: #c5cfe6; border-left: 2.5pt solid var(--navy); }}
  .fw-label {{ font-size: 7.4pt; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
               color: var(--navy); margin-bottom: 2pt; }}
  .fw-cols ul {{ padding-left: 11pt; margin-bottom: 4pt; }}
  .fw-cols li {{ margin: 1.5pt 0; }}
  blockquote {{ margin: 0 0 6pt; padding: 5pt 9pt; background: #fdf6e7; border-left: 2.5pt solid #b7791f;
                border-radius: 0 4pt 4pt 0; color: #5c4210; }}
  blockquote p {{ margin: 0; }}
  blockquote strong {{ color: #7a4d0b; }}

  table {{ width: 100%; border-collapse: collapse; margin: 4pt 0 10pt; font-size: 8.8pt;
           line-height: 1.4; break-inside: auto; }}
  th {{ background: var(--navy); color: #fff; text-align: left; font-weight: 600;
        padding: 5pt 7pt; }}
  td {{ padding: 5pt 7pt; border-bottom: .75pt solid var(--rule); vertical-align: top; }}
  tr {{ break-inside: avoid; }}
  tbody tr:nth-child(even) td {{ background: var(--tint); }}
  td a {{ border-bottom: none; }}

  code {{ font-family: Menlo, "SF Mono", Monaco, monospace; font-size: 8.4pt;
          background: var(--tint); padding: .5pt 2pt; border-radius: 2.5pt; }}
  pre {{ background: var(--tint); border: .75pt solid var(--rule); border-radius: 4pt;
         padding: 8pt 10pt; margin: 4pt 0 10pt; break-inside: avoid; overflow: hidden;
         font-size: 8.2pt; line-height: 1.4; }}
  pre code {{ background: none; padding: 0; font-size: inherit; line-height: inherit; }}

  /* the architecture diagram: first code block, wide box-drawing art */
  pre.diagram {{ background: #fff; padding: 12pt 0; font-size: 8.3pt; line-height: 1.17;
                 color: var(--ink); display: flex; justify-content: center; }}
</style></head>
<body>
  <div class="logos">
    <img src="{logo('investsync-logo')}" alt="InvestSync">
    <img class="cuhk" src="{logo('cuhksz-logo')}" alt="The Chinese University of Hong Kong, Shenzhen">
  </div>
  <div class="eyebrow">InvestSync Technology · Project Proposal</div>
  <h1>{title_main.strip()}<small>{title_sub.strip()}</small></h1>
  <div class="content">{body}</div>
</body></html>
"""

# Tag the box-drawing diagram so it gets its own sizing.
html = html.replace("<pre><code>                          [ Analyst", '<pre class="diagram"><code>                          [ Analyst', 1)

html_path = OUT.with_suffix(".html")
html_path.write_text(html, encoding="utf-8")

footer = """
<div style="width:100%; font-family: Helvetica Neue, Arial, sans-serif; font-size:7.5pt; color:#5b6475;
            padding: 0 17mm; display:flex; justify-content:space-between;">
  <span>InvestSync Research Tools · Project #3 · AY 2026/27</span>
  <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
</div>"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(html_path.as_uri())
    page.wait_for_load_state("networkidle")
    page.pdf(
        path=str(OUT),
        format="A4",
        print_background=True,
        prefer_css_page_size=True,
        display_header_footer=True,
        header_template="<span></span>",
        footer_template=footer,
    )
    browser.close()

print("wrote", OUT)
