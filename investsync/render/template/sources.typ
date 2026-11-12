// Source list of the student source pack (sources.pdf): the same content as the pack's sources text, with
// clickable links. Data: the blocks built by render/sources_pdf.py (text is data, never markup).
#let d = json(sys.inputs.at("data"))
#let navy = rgb("#1B3A8C")
#let muted = rgb("#5B6475")
#set document(title: d.title, author: "InvestSync Research Tools")
#set page(paper: "a4", margin: (x: 18mm, top: 16mm, bottom: 18mm),
  footer: context [#set text(size: 7.5pt, fill: muted); #d.footer #h(1fr) #counter(page).display("1 / 1", both: true)])
#set text(font: ("Inter", "Helvetica Neue", "Helvetica", "Arial", "PingFang SC",
                 "Hiragino Sans GB", "STHeiti", "Noto Sans CJK SC", "Noto Sans SC"), size: 9.5pt, lang: "en")
#set par(leading: 0.55em, spacing: 0.75em, justify: false)
#show link: set text(fill: navy)

#let runs(rs) = for r in rs {
  if "url" in r { link(r.url, text(size: 8pt, r.url)) }
  else if "code" in r { text(font: ("Menlo", "Courier New"), size: 8.5pt, r.code) }
  else { r.text }
}

#for b in d.blocks {
  if b.t == "h1" { block(below: 6pt, text(size: 16pt, weight: "bold", fill: navy, runs(b.runs))) }
  else if b.t == "h2" { block(above: 12pt, below: 5pt, text(size: 11.5pt, weight: "bold", fill: navy, runs(b.runs))) }
  else if b.t == "li" { block(above: 3pt, below: 3pt, inset: (left: 10pt), [#place(dx: -9pt)[•]#runs(b.runs)]) }
  else if b.t == "ol" { block(above: 3pt, below: 3pt, inset: (left: 14pt), [#place(dx: -14pt)[#b.n.]#runs(b.runs)]) }
  else if b.t == "hr" { line(length: 100%, stroke: 0.4pt + muted) }
  else { block(above: 4pt, below: 4pt, text(fill: if b.at("muted", default: false) { muted } else { black }, runs(b.runs))) }
}
