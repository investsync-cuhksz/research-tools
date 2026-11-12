// Picture-first teaching devices for the learner's guide: scale cards, the life-cycle diagram, the revenue / profit
// trend, the region map, the segment bar, the P/E history and the price-vs-value strip. Data arrive pre-computed from
// investsync/render/learner_visuals.py (positions already 0..1), so these functions only draw.
// Gotcha (as in lib.typ): never name a variable `v` or `h`.

#import "lib.typ": *

#let lv-orange = rgb("#E8590C")
#let lv-orange-tint = rgb("#FDF0E8")
#let lv-track = rgb("#EEF1F8")
#let lv-amber = rgb("#B7791F")
#let lv-return = rgb("#eda100")

#let lv-label(t) = text(size: 7.6pt, weight: "bold", fill: navy, tracking: 0.06em, upper(t))

// A 3- or 5-step scale as a segmented track: the chosen step is filled, the others are pale.
#let scale-track(levels, chosen, size: 6.9pt, ht: 17pt) = {
  let n = levels.len()
  grid(columns: (1fr,) * n, column-gutter: 2pt,
    ..levels.enumerate().map(((i, l)) => {
      let on = chosen != none and i == chosen
      box(width: 100%, height: ht, fill: if on { navy } else { lv-track },
        radius: if i == 0 { (left: 4pt) } else if i == n - 1 { (right: 4pt) } else { 0pt },
        stroke: if on { 1pt + navy } else { none },
        align(center + horizon, text(size: size, weight: if on { "bold" } else { "regular" },
          fill: if on { white } else { muted }, l)))
    }))
}

// A titled card: question, basis chip, the track and one sentence of evidence (plus an optional caveat)
#let scale-card(c, compact: false) = block(width: 100%, breakable: false, stroke: 0.6pt + rule-c, radius: 4pt,
  inset: (x: 8pt, y: 6pt), above: 6pt)[
  #grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(size: 9.6pt, weight: "bold", fill: navy, c.title),
    if c.basis != "" { box(fill: navy-tint, inset: (x: 4pt, y: 1.6pt), radius: 6pt, text(size: 6.6pt, fill: navy, c.basis)) }
    else { box(fill: lv-track, inset: (x: 4pt, y: 1.6pt), radius: 6pt, text(size: 6.6pt, fill: muted, "not scored")) })
  #v(1pt)
  #scale-track(c.levels, c.chosen)
  #v(1pt)
  #text(size: 8.8pt, c.evidence)
  #if c.at("caveat", default: none) != none [ \ #text(size: 7.8pt, fill: muted, style: "italic", c.caveat)]
]

// Yes / No / Mixed chip for the life-cycle questions
#let yn-chip(a) = {
  let (lab, col) = if a == "yes" { ("✓ Yes", pos-c) } else if a == "no" { ("✕ No", neg-c) }
    else if a == "mixed" { ("~ Mixed", lv-amber) } else { ("? No data", muted) }
  box(fill: col, inset: (x: 6pt, y: 3pt), radius: 8pt, text(size: 8pt, weight: "bold", fill: white, lab))
}

// Revenue and profit by year (+ TTM) on one axis: losses below the zero line in red
#let trend-bars(t, wd, ht, profit-label: "Operating profit") = {
  let pts = t.points
  let n = pts.len()
  let slot = wd / n
  let bw = slot * 0.3
  let top-pad = 10pt
  let zero-y = top-pad + ht * (1 - t.zero)
  box(width: wd, height: ht + top-pad + 14pt, {
    place(top + left, dx: 0pt, dy: zero-y, line(length: wd, stroke: 0.6pt + muted))
    for (i, p) in pts.enumerate() {
      let x0 = i * slot + slot / 2 - bw - 1pt
      let rh = calc.max(p.rev * ht, 0.6pt)
      place(top + left, dx: x0, dy: zero-y - rh, rect(width: bw, height: rh, fill: navy.transparentize(55%), radius: (top: 1.5pt)))
      place(top + left, dx: x0 - 8pt, dy: zero-y - rh - 8pt, box(width: bw + 16pt, align(center, text(size: 5.8pt, fill: navy, p.rev_t))))
      let ph = calc.max(calc.abs(p.prof) * ht, 0.6pt)
      let up = p.prof >= 0
      let x1 = x0 + bw + 2pt
      place(top + left, dx: x1, dy: if up { zero-y - ph } else { zero-y }, rect(width: bw, height: ph,
        fill: if up { pos-c } else { neg-c }, radius: if up { (top: 1.5pt) } else { (bottom: 1.5pt) }))
      place(top + left, dx: x1 - 8pt, dy: if up { zero-y - ph - 8pt } else { zero-y + ph + 1pt },
        box(width: bw + 16pt, align(center, text(size: 5.8pt, weight: "bold", fill: if up { pos-c } else { neg-c }, p.prof_t))))
      place(top + left, dx: i * slot, dy: top-pad + ht + 4pt, box(width: slot, align(center,
        text(size: 6.4pt, fill: if p.ttm { ink } else { muted }, weight: if p.ttm { "bold" } else { "regular" }, p.label))))
    }
  })
}

// The generic five-phase life-cycle picture with this company's phase highlighted
#let phase-diagram(ph, tag, wd, ht) = {
  let cw = wd / 5
  let head = 30pt
  let plot = ht - head
  let zero = head + plot * 0.58
  let up = plot * 0.52
  let dn = plot * 0.38
  let to-xy(p) = (p.at(0) * wd, if p.at(1) >= 0 { zero - p.at(1) * up } else { zero - p.at(1) * dn })
  let poly(pts, paint, w: 1.6pt, dash: none) = if pts.len() > 1 {
    let xy = pts.map(to-xy)
    place(top + left, curve(stroke: (paint: paint, thickness: w, cap: "round", join: "round", dash: dash),
      curve.move(xy.first()), ..xy.slice(1).map(q => curve.line(q))))
  }
  box(width: wd, height: ht + 4pt, {
    // columns: highlighted phase, a dashed outline for the borderline neighbour
    for i in range(5) {
      let on = ph.n == i + 1
      let alt = ph.alt != none and ph.alt == i + 1
      place(top + left, dx: i * cw, dy: 0pt, rect(width: cw, height: ht,
        fill: if on { lv-orange-tint } else if calc.even(i) { rgb("#FAFBFD") } else { white },
        stroke: if on { 1.4pt + lv-orange } else if alt { (paint: lv-orange, thickness: 0.9pt, dash: "dashed") } else { 0.4pt + rule-c }))
      let p = ph.phases.at(i)
      place(top + left, dx: i * cw, dy: 4pt, box(width: cw, align(center)[
        #box(circle(radius: 6pt, fill: if on { lv-orange } else { rule-c }, stroke: none,
          align(center + horizon, text(size: 7pt, weight: "bold", fill: if on { white } else { muted }, str(p.n)))))
        #h(2pt) #text(size: 7.4pt, weight: "bold", fill: if on { lv-orange } else { navy }, p.name)
      ]))
    }
    // zero line
    place(top + left, dx: 0pt, dy: zero, line(length: wd, stroke: (paint: muted, thickness: 0.7pt, dash: "dotted")))
    place(top + left, dx: wd - 52pt, dy: zero + 2pt, box(width: 48pt, align(right, text(size: 5.8pt, fill: muted, "zero profit"))))
    let d = ph.diagram
    poly(d.revenue, navy, w: 1.8pt)
    poly(d.loss, neg-c)
    poly(d.profit, pos-c)
    poly(d.returned, lv-return, dash: "dashed")
    // curve labels and two landmarks
    let lab(p, body) = { let q = to-xy(p); place(top + left, dx: q.at(0), dy: q.at(1), body) }
    lab((0.25, 0.36), text(size: 6.4pt, weight: "bold", fill: navy, "Revenue"))
    lab((0.655, 0.62), text(size: 6.4pt, weight: "bold", fill: pos-c, "Profit"))
    lab((0.13, -0.42), text(size: 6.2pt, fill: neg-c, "Losses"))
    lab((0.62, -0.08), text(size: 6.2pt, weight: "bold", fill: lv-amber, "Dividends + buybacks"))
    lab((0.405, -0.1), text(size: 5.8pt, fill: muted, "breakeven"))
    // "you are here" tag at the bottom of the highlighted column
    place(top + left, dx: (ph.n - 1) * cw, dy: ht - 15pt, box(width: cw, align(center,
      box(fill: lv-orange, inset: (x: 5pt, y: 2.5pt), radius: 6pt, text(size: 7pt, weight: "bold", fill: white, tag)))))
    if ph.alt != none {
      place(top + left, dx: (ph.alt - 1) * cw, dy: ht - 14pt, box(width: cw, align(center,
        text(size: 6.2pt, fill: lv-orange, style: "italic", "borderline"))))
    }
  })
}

// Revenue by segment: one stacked bar and a small table (share, revenue, 1-year growth when the data has it)
#let seg-bar(s, wd) = {
  let bh = 14pt
  box(width: wd, height: bh, radius: 3pt, clip: true, {
    let x = 0pt
    for it in s.items {
      let w = it.share * wd
      place(top + left, dx: x, dy: 0pt, rect(width: w, height: bh, fill: rgb(it.color), stroke: 0.5pt + white))
      if it.share >= 0.08 {
        place(top + left, dx: x, dy: 3pt, box(width: w, align(center, text(size: 7pt, weight: "bold", fill: white, it.share_t))))
      }
      x += w
    }
  })
  v(3pt)
  let cols = if s.has_growth { (8pt, 1fr, auto, auto, auto) } else { (8pt, 1fr, auto, auto) }
  table(columns: cols, stroke: none, inset: (x: 3pt, y: 1.8pt), align: (left + horizon, left + horizon, right, right, right),
    table.hline(stroke: 0.4pt + rule-c),
    [], text(size: 7pt, fill: muted)[Segment (#s.period)], text(size: 7pt, fill: muted)[Share],
    text(size: 7pt, fill: muted)[Revenue (#s.currency)], ..if s.has_growth { (text(size: 7pt, fill: muted)[1-yr],) } else { () },
    ..s.items.map(it => (box(width: 6pt, height: 6pt, radius: 1.5pt, fill: rgb(it.color)), text(size: 8pt, it.name),
      text(size: 8pt, weight: "bold", it.share_t), text(size: 8pt, it.rev_t),
      ..if s.has_growth { (text(size: 8pt, signed(it.growth_t)),) } else { () })).flatten())
  if s.note != "" { text(size: 7pt, fill: muted, s.note) }
}

// Revenue by region on the world map, with the legend
#let geo-block(m, wd) = {
  image(bytes(m.svg), format: "svg", width: wd)
  v(-2pt)
  let items = m.legend.map(it => box[
    #if it.mapped { box(width: 8pt, height: 8pt, radius: 1.5pt, fill: rgb(it.color), baseline: 1pt) } else { box(width: 8pt, height: 8pt, radius: 1.5pt, stroke: (paint: muted, thickness: 0.6pt, dash: "dotted"), baseline: 1pt) }
    #h(2pt)#text(size: 8pt)[#it.name · *#it.share_t*]#if not it.mapped { text(size: 7pt, fill: muted)[ (not on the map)] }
  ])
  align(center, items.join(h(10pt)))
}

// P/E over five years against five bands of its own history
#let pe-chart(c, wd, ht) = {
  let gutter = 30pt
  let rgap = 96pt
  let pw = wd - gutter - rgap
  let fills = (rgb("#DCEFE3"), rgb("#EDF6F0"), rgb("#F4F5F7"), rgb("#FBEDEC"), rgb("#F6DCDA"))
  let names = ("much cheaper than usual", "cheaper than usual", "about usual", "dearer than usual", "much dearer than usual")
  let edges = (0,) + c.bands + (1,)
  box(width: wd, height: ht + 16pt, inset: (top: 4pt), {
    for i in range(5) {
      let y0 = ht - edges.at(i + 1) * ht
      let hh = (edges.at(i + 1) - edges.at(i)) * ht
      place(top + left, dx: gutter, dy: y0, rect(width: pw, height: hh, fill: fills.at(i), stroke: none))
      if hh > 6pt {
        place(top + left, dx: gutter + pw + 4pt, dy: y0 + hh / 2 - 3.5pt, text(size: 6pt, fill: muted, names.at(i)))
      }
    }
    for t in c.yticks {
      let yy = ht - t.at(0) * ht
      place(top + left, dx: 0pt, dy: yy - 3pt, box(width: gutter - 4pt, align(right, text(size: 5.8pt, fill: muted, t.at(1)))))
      place(top + left, dx: gutter, dy: yy, line(length: pw, stroke: 0.3pt + white))
    }
    let pts = c.points.map(p => (gutter + p.at(0) * pw, ht - p.at(1) * ht))
    place(top + left, curve(stroke: (paint: navy, thickness: 1.1pt, join: "round"),
      curve.move(pts.first()), ..pts.slice(1).map(q => curve.line(q))))
    let last = pts.last()
    place(top + left, dx: last.at(0) - 3pt, dy: last.at(1) - 3pt, circle(radius: 3pt, fill: lv-orange, stroke: 1pt + white))
    place(top + left, dx: last.at(0) - 52pt, dy: last.at(1) - 14pt, box(width: 50pt, align(right,
      text(size: 7pt, weight: "bold", fill: lv-orange)[now #c.current_t])))
    for l in c.xlabels {
      let xx = gutter + l.at(0) * pw
      place(top + left, dx: xx - 10pt, dy: ht + 3pt, box(width: 20pt, align(center, text(size: 6pt, fill: muted, l.at(1)))))
    }
  })
}

// Price against the model's value (bear / base / bull and the fair value)
#let value-strip(r, wd) = {
  let ht = 46pt
  let ty = 22pt
  box(width: wd, height: ht, {
    place(top + left, dx: 0pt, dy: ty, rect(width: wd, height: 6pt, fill: lv-track, radius: 3pt))
    if r.range != none {
      let x0 = r.range.at(0) * wd
      let x1 = r.range.at(1) * wd
      place(top + left, dx: x0, dy: ty, rect(width: x1 - x0, height: 6pt, fill: navy.transparentize(70%), radius: 3pt))
    }
    let px = r.price_x * wd
    // the price and fair-value labels sit on the same line above the bar: when the two values are close, each label
    // moves to its own side of its marker instead of centring on it (they overlapped at +13% upside, 11 Nov 2026)
    let fx = none
    for m in r.marks { if m.kind != "scen" { fx = m.x * wd } }
    let close = fx != none and calc.abs(fx - px) < 80pt
    let side(x, other) = if not close { (x - 40pt, center) } else if x >= other { (x - 2pt, left) } else { (x - 78pt, right) }
    for m in r.marks {
      let x = m.x * wd
      if m.kind == "scen" {
        place(top + left, dx: x - 0.6pt, dy: ty - 2pt, rect(width: 1.2pt, height: 10pt, fill: navy))
        place(top + left, dx: x - 30pt, dy: ty + 10pt, box(width: 60pt, align(center, text(size: 6.6pt, fill: navy)[#m.label #m.t])))
      } else {
        place(top + left, dx: x - 3.5pt, dy: ty - 1pt, rotate(45deg, rect(width: 7pt, height: 7pt, fill: navy, stroke: 0.8pt + white)))
        let (dx, al) = side(x, px)
        place(top + left, dx: dx, dy: ty - 21pt, box(width: 80pt, align(al, text(size: 6.8pt, weight: "bold", fill: navy)[#m.label #m.t])))
      }
    }
    place(top + left, dx: px - 0.9pt, dy: ty - 9pt, rect(width: 1.8pt, height: 22pt, fill: lv-orange))
    let (pdx, pal) = side(px, if fx == none { px } else { fx })
    place(top + left, dx: pdx, dy: ty - 19pt, box(width: 80pt, align(pal, text(size: 6.8pt, weight: "bold", fill: lv-orange)[Price #r.price_t])))
  })
}

// Two cards side by side with equal heights (a block with height: 100% in a grid would take the whole page)
#let card-pair(a, b, ratio: (1, 1), gutter: 10pt, pad: 9pt, style-a: (:), style-b: (:)) = layout(sz => {
  let total = sz.width - gutter
  let wa = total * ratio.at(0) / (ratio.at(0) + ratio.at(1))
  let wb = total - wa
  let ha = measure(block(width: wa, inset: pad, a)).height
  let hb = measure(block(width: wb, inset: pad, b)).height
  let hh = calc.max(ha, hb)
  grid(columns: (wa, wb), column-gutter: gutter,
    block(width: wa, height: hh, inset: pad, radius: 4pt, ..style-a, a),
    block(width: wb, height: hh, inset: pad, radius: 4pt, ..style-b, b))
})
