// Shared styles, helpers and charts for the InvestSync full report (pages 2+).
// Chart specs arrive pre-computed from investsync/render/report_vm.py: positions are already
// normalised to 0..1, so these functions only draw. No Typst packages are used.
// Gotcha: never name a variable `v` or `h` here (they shadow Typst's spacing functions).

#let navy = rgb("#1B3A8C")
#let navy-tint = rgb("#EEF1F8")
#let ink = rgb("#1D2433")
#let muted = rgb("#5B6475")
#let rule-c = rgb("#D9DEE8")
#let grid-c = rgb("#E6E9EF")
#let pos-c = rgb("#1E7B4F")
#let neg-c = rgb("#B3261E")
// validated categorical order (light surface) + de-emphasis grey
#let s1 = rgb("#2a78d6")
#let s2 = rgb("#eb6834")
#let s3 = rgb("#1baf7a")
#let s4 = rgb("#eda100")
#let rest = rgb("#b9bfca")
// status (always shown with a label)
#let st-good = rgb("#0ca30c")
#let st-warn = rgb("#fab219")
#let st-crit = rgb("#d03b3b")
#let ai-c = rgb("#5a4bbd")
#let ai-tint = rgb("#F5F3FC")

// Run a chart function at the full width of the current container
#let fit(f) = layout(sz => f(sz.width))

// ---------------------------------------------------------------- text helpers
#let signed(s) = {
  if type(s) != str { s }
  else if s.starts-with("+") { text(fill: pos-c, s) }
  else if s.starts-with("-") and s != "–" { text(fill: neg-c, s) }
  else { s }
}

#let chip(label, fill: navy, fg: white) = box(fill: fill, inset: (x: 2.8pt, y: 1.3pt), radius: 1.5pt,
  text(size: 5.6pt, weight: "bold", fill: fg, tracking: 0.04em, upper(label)))

#let chapter(num, title, sub: none) = block(sticky: true, above: 2pt, below: 7pt, width: 100%)[
  #grid(columns: (auto, 1fr), column-gutter: 6pt, align: (left + bottom, left + bottom),
    text(size: 15pt, weight: "bold", fill: s1, num),
    [#text(size: 13pt, weight: "bold", fill: navy, title)#if sub != none [ #h(4pt) #text(size: 7pt, fill: muted, sub)]])
  #v(-3pt)
  #line(length: 100%, stroke: 1.3pt + navy)
]

#let section(title, body, breakable: false, note: none) = block(width: 100%, breakable: breakable, above: 9pt)[
  #block(sticky: true, below: 3pt)[
    #text(size: 7pt, weight: "bold", fill: navy, tracking: 0.08em)[#upper(title)]
    #if note != none [#h(4pt) #text(size: 6pt, fill: muted, note)]
  ]
  #line(length: 100%, stroke: 0.6pt + navy)
  #v(2.5pt)
  #body
]

#let small-note(body) = block(above: 3pt, text(size: 5.8pt, fill: muted, body))

#let kv(rows, label-fill: muted, bold-last: false, size: 7pt, columns: (1fr, auto)) = table(
  columns: columns, stroke: none, inset: (x: 0pt, y: 1.6pt), column-gutter: 6pt,
  ..rows.enumerate().map(((i, r)) => {
    let last = bold-last and i == rows.len() - 1
    (text(size: size, fill: if last { ink } else { label-fill }, weight: if last { "bold" } else { "regular" }, r.at(0)),
     align(right, text(size: size, weight: if last { "bold" } else { "regular" }, signed(r.at(1)))))
  }).flatten()
)

// Fiscal-year table: rows of {label, values, style}
#let year-table(years, rows, label: "", label-col: 1.9fr, extra: none) = {
  let ny = years.len()
  table(
    columns: (label-col,) + (1fr,) * ny,
    stroke: none, inset: (x: 3pt, y: 1.75pt),
    align: (left,) + (right,) * ny,
    fill: (_, row) => if row == 0 { navy } else if calc.even(row) { navy-tint } else { none },
    table.header(text(fill: white, weight: "bold", label), ..years.map(y => text(fill: white, weight: "bold", y))),
    ..rows.map(r => {
      let sty(s) = if r.style == "bold" { strong(signed(s)) } else if r.style == "sub" { text(fill: muted, size: 6.6pt, signed(s)) } else if r.style == "muted" { text(fill: muted, signed(s)) } else { signed(s) }
      (sty(r.label),) + r.values.map(x => sty(x))
    }).flatten()
  )
}

#let legend(items) = if items.len() > 0 {
  block(below: 2pt, items.map(it => box[#box(width: 7pt, height: 2.2pt, fill: rgb(it.at(1)), radius: 1pt, baseline: -1.2pt) #h(1.5pt)#text(size: 5.8pt, fill: muted, it.at(0))]).join(h(7pt)))
}

#let chart-title(t) = block(below: 2pt, text(size: 6.6pt, weight: "bold", fill: ink, t))

// ---------------------------------------------------------------- AI sections
// Data-only edition (12 Nov 2026): the reader's own analysis goes where the AI text would be: the section, the
// question to answer and ruled space to write in (sec.lines lines)
#let write-box(sec) = block(width: 100%, breakable: false, above: 6pt, below: 4pt,
  stroke: 0.6pt + rule-c, radius: 2pt, inset: (x: 6pt, top: 4.5pt, bottom: 5pt))[
  #chip("Your analysis", fill: navy) #h(3pt) #text(size: 7pt, weight: "bold", fill: navy, sec.title) \
  #v(-1pt)
  #text(size: 6.4pt, fill: muted, sec.desc)
  #for i in range(sec.at("lines", default: 4)) {
    block(above: 13pt, below: 0pt, line(length: 100%, stroke: (paint: rule-c, thickness: 0.6pt, dash: "dotted")))
  }
]

#let ai-box(sec, status: "placeholder") = {
  if status == "data_only" {
    write-box(sec)
  } else if sec.value != none {
    block(width: 100%, inset: (left: 6pt, y: 2pt), stroke: (left: 1.6pt + ai-c), breakable: true)[
      // no "AI-written" chip on every section (round-7 review: labels read as scaffolding; the disclosures and the
      // page-1 footer state that the commentary is AI-written); a flagged section keeps its warning
      #if status == "flagged" { chip("AI · flagged for review", fill: st-crit); v(1pt) }
      #if type(sec.value) == array {
        for it in sec.value {
          if type(it) == dictionary [- *#it.title.* #it.text] else [- #it]
        }
      } else { par(justify: true, sec.value) }
    ]
  } else if status != "placeholder" {
    // the AI step ran but this section did not pass its checks and was left out: show nothing rather than a
    // "pending" box, which a reader takes for an unfinished report (round-10 review, 11 Nov 2026)
    none
  } else {
    block(width: 100%, fill: ai-tint, inset: (x: 6pt, y: 4.5pt), radius: 2pt,
      stroke: (paint: rgb("#C8C1EC"), thickness: 0.6pt, dash: "dashed"))[
      #chip("AI section · pending", fill: ai-c) #h(3pt) #text(size: 7pt, weight: "bold", fill: ai-c, sec.title) \
      #v(-1pt)
      #text(size: 6.4pt, fill: muted)[#sec.desc Written by the AI step once it is configured; every figure is checked against the data before it is shown.]
    ]
  }
}

// ---------------------------------------------------------------- charts
#let _ylabels(ticks, gutter, pw, ht) = {
  for t in ticks {
    let yy = ht - t.at(0) * ht
    place(top + left, dx: gutter, dy: yy, line(length: pw, stroke: 0.35pt + grid-c))
    place(top + left, dx: 0pt, dy: yy - 3pt, box(width: gutter - 3pt, align(right, text(size: 5.3pt, fill: muted, t.at(1)))))
  }
}

// Grouped vertical bars on one axis
#let bar-chart(c, wd, ht) = {
  let gutter = 26pt
  let pw = wd - gutter
  let n = c.cats.len()
  let k = c.series.len()
  let slot = pw / n
  let group = slot * 0.74
  let bw = group / k
  box(width: wd, height: ht + 15pt, inset: (top: 5pt), {
    _ylabels(c.yticks, gutter, pw, ht)
    for (i, cat) in c.cats.enumerate() {
      let x0 = gutter + i * slot + (slot - group) / 2
      for (j, s) in c.series.enumerate() {
        let b = s.bars.at(i)
        if b != none {
          let top-y = ht - b.at(1) * ht
          let bh = calc.max((b.at(1) - b.at(0)) * ht, 0.4pt)
          let up = b.at(0) >= c.zero - 0.0001
          place(top + left, dx: x0 + j * bw + 0.7pt, dy: top-y,
            rect(width: bw - 1.4pt, height: bh, fill: rgb(s.color), stroke: none,
                 radius: if up { (top: 1.2pt) } else { (bottom: 1.2pt) }))
        }
      }
      place(top + left, dx: gutter + i * slot, dy: ht + 2.5pt, box(width: slot, align(center, text(size: 5.5pt, fill: muted, cat))))
    }
    place(top + left, dx: gutter, dy: ht - c.zero * ht, line(length: pw, stroke: 0.5pt + muted))
  })
}

// Lines over fiscal years, one axis, labelled at the end
#let line-chart(c, wd, ht) = {
  let gutter = 26pt
  let right = 50pt
  let pw = wd - gutter - right
  let n = c.cats.len()
  box(width: wd, height: ht + 15pt, inset: (top: 5pt), {
    _ylabels(c.yticks, gutter, pw, ht)
    if c.zero != none { place(top + left, dx: gutter, dy: ht - c.zero * ht, line(length: pw, stroke: 0.5pt + muted)) }
    for s in c.series {
      let pts = s.points.map(p => (gutter + p.at(0) * pw, ht - p.at(1) * ht))
      if pts.len() > 1 {
        place(top + left, curve(stroke: (paint: rgb(s.color), thickness: 1.2pt, join: "round", cap: "round"),
          curve.move(pts.first()), ..pts.slice(1).map(p => curve.line(p))))
      }
      for p in pts {
        place(top + left, dx: p.at(0) - 1.5pt, dy: p.at(1) - 1.5pt, circle(radius: 1.5pt, fill: rgb(s.color), stroke: 0.6pt + white))
      }
      let ly = ht - s.end_y * ht
      place(top + left, dx: gutter + pw + 3pt, dy: ly - 3pt, text(size: 5.4pt, fill: ink, s.end_label))
    }
    for (i, cat) in c.cats.enumerate() {
      place(top + left, dx: gutter + i * pw / n, dy: ht + 2.5pt, box(width: pw / n, align(center, text(size: 5.5pt, fill: muted, cat))))
    }
  })
}

// Time series (x in 0..1 of the date range). series: (name, color, points, w)
#let time-chart(series, yticks, xlabels, wd, ht, refs: (), band: none, gutter: 26pt) = {
  let pw = wd - gutter
  box(width: wd, height: ht + 15pt, inset: (top: 5pt), {
    _ylabels(yticks, gutter, pw, ht)
    if band != none {
      place(top + left, dx: gutter, dy: ht - band.at(1) * ht,
        rect(width: pw, height: (band.at(1) - band.at(0)) * ht, fill: rgb("#2a78d6").transparentize(88%), stroke: none))
    }
    for r in refs {
      let yy = ht - r.at(0) * ht
      place(top + left, dx: gutter, dy: yy, line(length: pw, stroke: (paint: rgb(r.at(2)), thickness: 0.7pt, dash: "dashed")))
      place(top + left, dx: gutter + 2pt, dy: yy - 7pt, text(size: 5.3pt, fill: muted, r.at(1)))
    }
    for s in series {
      let pts = s.points.map(p => (gutter + p.at(0) * pw, ht - p.at(1) * ht))
      if pts.len() > 1 {
        place(top + left, curve(stroke: (paint: rgb(s.color), thickness: s.w * 1pt, join: "round"),
          curve.move(pts.first()), ..pts.slice(1).map(p => curve.line(p))))
      }
    }
    for l in xlabels {
      let xx = gutter + l.at(0) * pw
      place(top + left, dx: xx, dy: ht, line(length: 2pt, angle: 90deg, stroke: 0.4pt + muted))
      place(top + left, dx: xx - 8pt, dy: ht + 2.5pt, box(width: 16pt, align(center, text(size: 5.4pt, fill: muted, l.at(1)))))
    }
  })
}

// Thin bar strip (volume) aligned with a time chart
#let strip-bars(pts, wd, ht, gutter: 26pt, color: rest) = {
  let pw = wd - gutter
  let bw = calc.max(pw / calc.max(pts.len(), 1) - 0.4pt, 0.5pt)
  box(width: wd, height: ht, {
    for p in pts {
      place(top + left, dx: gutter + p.at(0) * pw - bw / 2, dy: ht - p.at(1) * ht, rect(width: bw, height: p.at(1) * ht, fill: color, stroke: none))
    }
    place(top + left, dx: gutter, dy: ht, line(length: pw, stroke: 0.4pt + muted))
  })
}

// Football field: horizontal value ranges per method, price line
#let football(ff, wd) = {
  let lw = 88pt
  let vw = 70pt
  let pw = wd - lw - vw
  let rh = 15pt
  let n = ff.bars.len()
  let top-pad = 9pt
  let hh = n * rh
  let has-fair = "fair_x" in ff
  box(width: wd, height: hh + top-pad + if has-fair { 21pt } else { 12pt }, {
    for t in ff.ticks {
      let xx = lw + t.at(0) * pw
      place(top + left, dx: xx, dy: top-pad, line(start: (0pt, 0pt), end: (0pt, hh), stroke: 0.35pt + grid-c))
      place(top + left, dx: xx - 12pt, dy: top-pad + hh + 2.5pt, box(width: 24pt, align(center, text(size: 5.4pt, fill: muted, t.at(1)))))
    }
    for (i, b) in ff.bars.enumerate() {
      let yy = top-pad + i * rh
      place(top + left, dx: 0pt, dy: yy + 4pt, box(width: lw - 5pt, text(size: 6.3pt, fill: ink, b.label)))
      place(top + left, dx: lw + b.x0 * pw, dy: yy + 3.5pt,
        rect(width: calc.max((b.x1 - b.x0) * pw, 1.5pt), height: rh - 7pt, fill: s1.transparentize(15%), radius: 1.6pt, stroke: none))
      if b.mid != none {
        place(top + left, dx: lw + b.mid * pw - 0.7pt, dy: yy + 2pt, rect(width: 1.4pt, height: rh - 4pt, fill: ink, stroke: none))
      }
      place(top + left, dx: lw + pw + 5pt, dy: yy + 4pt, text(size: 5.9pt, fill: ink, b.low + " – " + b.high))
    }
    if has-fair {
      let fx = lw + ff.fair_x * pw
      place(top + left, dx: fx, dy: top-pad - 2pt, line(start: (0pt, 0pt), end: (0pt, hh + 2pt), stroke: (paint: navy, thickness: 1pt, dash: "dashed")))
      place(top + left, dx: fx - 45pt, dy: top-pad + hh + 11pt, box(width: 90pt, align(center, text(size: 5.6pt, weight: "bold", fill: navy, ff.fair_label))))
    }
    let px = lw + ff.price_x * pw
    place(top + left, dx: px, dy: top-pad - 2pt, line(start: (0pt, 0pt), end: (0pt, hh + 2pt), stroke: 1pt + neg-c))
    place(top + left, dx: px - 40pt, dy: -1pt, box(width: 80pt, align(center, text(size: 5.6pt, weight: "bold", fill: neg-c, ff.price_label))))
  })
}

// Histogram with price and median markers
#let histogram(m, wd, ht) = {
  let n = m.bars.len()
  let bw = wd / n
  box(width: wd, height: ht + 20pt, {
    let base = 8pt
    for (i, f) in m.bars.enumerate() {
      if f > 0 {
        place(top + left, dx: i * bw + 0.6pt, dy: base + ht - f * ht, rect(width: bw - 1.2pt, height: f * ht, fill: s1, radius: (top: 1pt), stroke: none))
      }
    }
    place(top + left, dx: 0pt, dy: base + ht, line(length: wd, stroke: 0.5pt + muted))
    for t in m.ticks {
      place(top + left, dx: t.at(0) * wd - 12pt, dy: base + ht + 2.5pt, box(width: 24pt, align(center, text(size: 5.4pt, fill: muted, t.at(1)))))
    }
    let mx = m.p50_x * wd
    place(top + left, dx: mx, dy: base, line(start: (0pt, 0pt), end: (0pt, ht), stroke: 0.8pt + ink))
    place(top + left, dx: mx + 2pt, dy: base, text(size: 5.4pt, fill: ink, "median"))
    let px = m.price_x * wd
    place(top + left, dx: px, dy: base - 6pt, line(start: (0pt, 0pt), end: (0pt, ht + 6pt), stroke: 1pt + neg-c))
    place(top + left, dx: px - 30pt, dy: -1pt, box(width: 60pt, align(center, text(size: 5.5pt, weight: "bold", fill: neg-c, if m.price_inside { "Price" } else { "Price (off scale)" }))))
  })
}

// Scatter: target highlighted, peers de-emphasised, peer medians as reference lines
#let scatter(sc, wd, ht, xlabel: "", ylabel: "") = {
  let gutter = 26pt
  let pw = wd - gutter - 8pt
  box(width: wd, height: ht + 23pt, inset: (top: 5pt), {
    _ylabels(sc.yticks, gutter, pw, ht)
    for t in sc.xticks {
      let xx = gutter + t.at(0) * pw
      place(top + left, dx: xx, dy: 0pt, line(start: (0pt, 0pt), end: (0pt, ht), stroke: 0.35pt + grid-c))
      place(top + left, dx: xx - 10pt, dy: ht + 2.5pt, box(width: 20pt, align(center, text(size: 5.3pt, fill: muted, t.at(1)))))
    }
    if sc.median_x != none { place(top + left, dx: gutter + sc.median_x * pw, dy: 0pt, line(start: (0pt, 0pt), end: (0pt, ht), stroke: (paint: muted, thickness: 0.5pt, dash: "dashed"))) }
    if sc.median_y != none { place(top + left, dx: gutter, dy: ht - sc.median_y * ht, line(length: pw, stroke: (paint: muted, thickness: 0.5pt, dash: "dashed"))) }
    for p in sc.points.sorted(key: p => if p.target { 1 } else { 0 }) {
      let xx = gutter + p.x * pw
      let yy = ht - p.y * ht
      let col = if p.target { s1 } else { rest }
      place(top + left, dx: xx - 3pt, dy: yy - 3pt, circle(radius: 3pt, fill: col, stroke: 1pt + white))
      place(top + left, dx: xx + 4pt, dy: yy - 3.9pt, box(fill: white, inset: (x: 0.8pt, y: 0.5pt), radius: 1pt,
        text(size: 5.5pt, fill: if p.target { ink } else { muted }, weight: if p.target { "bold" } else { "regular" }, p.label)))
    }
    place(top + left, dx: gutter + pw - 80pt, dy: ht + 10pt, box(width: 80pt, align(right, text(size: 5.5pt, fill: muted, xlabel))))
  })
}

// Horizontal share bars: items of {label, frac, text}
#let hbars(items, wd, label-w: 70pt, value-w: 34pt, color: s1, size: 6.3pt) = {
  let tw = wd - label-w - value-w
  grid(columns: (label-w, tw, value-w), row-gutter: 3.2pt, align: (left + horizon, left + horizon, right + horizon),
    ..items.map(it => (
      text(size: size, it.label),
      box(width: tw, height: 6pt, fill: grid-c, radius: 1.5pt,
        place(top + left, box(width: calc.max(it.frac, 0) * tw, height: 6pt, fill: color, radius: 1.5pt))),
      text(size: size, it.text),
    )).flatten())
}

#let status-chip(s) = {
  if s == "pass" { chip("✓ pass", fill: st-good) }
  else if s == "caveat" { chip("! caveat", fill: st-warn, fg: ink) }
  else if s == "fail" { chip("✕ fail", fill: st-crit) }
  else { chip("i info", fill: rest, fg: ink) }
}

#let rating-colour(r) = if r == "Buy" { pos-c } else if r == "Outperform" { rgb("#4F9A6E") } else if r == "Hold" { rgb("#8A6D1F") } else if r == "Underperform" { rgb("#C8574F") } else if r == "Sell" { neg-c } else { muted }
#let rating-badge(r, size: 13pt) = box(fill: rating-colour(r), inset: (x: 7pt, y: 4pt), radius: 2pt,
  text(size: size, weight: "bold", fill: white, upper(r)))
