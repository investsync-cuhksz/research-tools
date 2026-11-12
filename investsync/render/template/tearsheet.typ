// InvestSync Research Tools: one-page A4 equity tear sheet.
// Data arrives as a view-model JSON (see investsync/render/viewmodel.py);
// every number is pre-formatted in Python, so this file only lays things out.

#let vm = json(sys.inputs.at("data"))

#let navy = rgb("#1B3A8C")
#let navy-tint = rgb("#EEF1F8")
#let ink = rgb("#1D2433")
#let muted = rgb("#5B6475")
#let rule-c = rgb("#D9DEE8")
#let stock-c = rgb("#2a78d6")
#let bench-c = rgb("#eb6834")
#let pos-c = rgb("#1E7B4F")
#let neg-c = rgb("#B3261E")

#set document(title: vm.company.name + " (" + vm.company.ticker + ") · InvestSync Tear Sheet",
              author: "InvestSync Research Tools") if sys.inputs.at("layout", default: "tearsheet") == "tearsheet"
#set page(
  paper: "a4",
  margin: (x: 11mm, top: 9mm, bottom: 9mm),
)
#set text(font: ("Inter", "Helvetica Neue", "Helvetica", "Arial", "PingFang SC",
                 "Hiragino Sans GB", "STHeiti", "Noto Sans CJK SC", "Noto Sans SC"),
          size: 7.6pt, fill: ink, lang: "en")
#set par(leading: 0.48em, spacing: 0.7em, justify: false)

// ---------- helpers ----------
// learner layout: orange step markers (1-8) that match the learner's guide
#let learner-layout = sys.inputs.at("layout", default: "tearsheet") == "learner"
#let mk(..ns) = if learner-layout {
  for n in ns.pos() { box(baseline: 1.2pt, circle(radius: 4.2pt, fill: rgb("#E8590C"), stroke: none, align(center + horizon, text(size: 5.8pt, weight: "bold", fill: white, n)))) + h(1.5pt) }
}
#let section(title, body, mark: ()) = block(width: 100%, breakable: false)[
  #block(below: 2.8pt)[
    #mk(..mark)#text(size: 7pt, weight: "bold", fill: navy, tracking: 0.08em)[#upper(title)]
  ]
  #line(length: 100%, stroke: 0.7pt + navy)
  #v(1.8pt)
  #body
]

#let signed(s) = {
  if s.starts-with("+") { text(fill: pos-c, s) }
  else if s.starts-with("-") { text(fill: neg-c, s) }
  else { s }
}

// data-only edition (12 Nov 2026): no AI text and no rating; each AI section becomes a box for the reader's own view
#let data-only = vm.at("data_only", default: false)
#let write-space(a) = block(width: 100%, breakable: false, above: 2pt, below: 2pt,
  stroke: 0.6pt + rule-c, radius: 2pt, inset: (x: 5pt, top: 3.5pt, bottom: 4pt))[
  #box(fill: navy, inset: (x: 2.6pt, y: 1.3pt), radius: 1.5pt,
    text(fill: white, weight: "bold", size: 5.4pt, tracking: 0.05em, "YOUR ANALYSIS"))
  #h(2pt) #text(size: 6.3pt, fill: muted, a.desc)
  #for i in range(a.lines) {
    block(above: 10.5pt, below: 0pt, line(length: 100%, stroke: (paint: rule-c, thickness: 0.6pt, dash: "dotted")))
  }
]

#let status-note = if vm.narrative == none or vm.narrative.status == "placeholder" {
  block(fill: rgb("#FDF6E7"), inset: 4pt, radius: 2pt, width: 100%,
    text(size: 6.6pt, fill: rgb("#7A4D0B"))[*Commentary not generated.* Numbers above are final; the analyst commentary needs the AI step, which was not run for this sheet.])
} else if vm.narrative.status == "flagged" {
  block(fill: rgb("#FCECEA"), inset: 4pt, radius: 2pt, width: 100%,
    text(size: 6.6pt, fill: neg-c)[*Flagged for review:* the commentary quotes figures that do not match the data. Do not distribute until checked.])
} else { none }

#let has(field) = vm.narrative != none and vm.narrative.at(field).len() > 0
#let rating-col(r) = if r == "Buy" { pos-c } else if r == "Outperform" { rgb("#4F9A6E") } else if r == "Hold" { rgb("#8A6D1F") } else if r == "Underperform" { rgb("#C8574F") } else if r == "Sell" { neg-c } else { muted }

#let bullet(label, b, colour) = block(below: 3.6pt)[
  #set text(size: 7pt)
  #box(fill: colour, inset: (x: 2.6pt, y: 1.4pt), radius: 1.5pt,
    text(fill: white, weight: "bold", size: 6.4pt, label))
  #h(2pt) *#b.title.* #b.text
]

// ---------- line chart (no external packages) ----------
#let line-chart(c, w, h) = {
  let y(v) = h - (v - c.ymin) / (c.ymax - c.ymin) * h
  let x(t) = t * w
  box(width: w, height: h + 9pt, {
    for t in c.yticks {
      let yy = y(t.at(0))
      place(top + left, line(start: (0pt, yy), end: (w, yy),
        stroke: (paint: if t.at(0) == 100 { rule-c } else { rgb("#E6E9EF") }, thickness: if t.at(0) == 100 { 0.6pt } else { 0.35pt })))
      place(top + left, dx: w + 2pt, dy: yy - 3pt, text(size: 5.6pt, fill: muted, t.at(1)))
    }
    for l in c.xlabels {
      place(top + left, dx: x(l.at(0)), dy: h, line(length: 2pt, angle: 90deg, stroke: 0.4pt + muted))
      place(top + left, dx: x(l.at(0)) - 6pt, dy: h + 2.5pt, text(size: 5.6pt, fill: muted, l.at(1)))
    }
    for (series, colour, weight) in ((c.bench, bench-c, 0.8pt), (c.stock, stock-c, 1.1pt)) {
      let pts = series.map(p => (x(p.at(0)), y(p.at(1))))
      place(top + left, curve(
        stroke: (paint: colour, thickness: weight, join: "round"),
        curve.move(pts.first()),
        ..pts.slice(1).map(p => curve.line(p)),
      ))
    }
  })
}

// ---------- header ----------
#grid(
  columns: (auto, 1fr),
  align: (left + horizon, right + horizon),
  image("../assets/investsync-logo.png", height: 8.5mm),
  [
    #text(size: 6.8pt, weight: "bold", fill: navy, tracking: 0.12em)[#if data-only [EQUITY RESEARCH · DATA EDITION] else [EQUITY RESEARCH · TEAR SHEET]] \
    #text(size: 6.8pt, fill: muted)[InvestSync Technology · #vm.date]
  ],
)
#v(-1pt)
#line(length: 100%, stroke: 1.6pt + navy)
#v(3pt)

// ---------- title + quote box ----------
#grid(
  columns: (1fr, 62mm),
  column-gutter: 8pt,
  [
    #let long-name = vm.company.name.len() + vm.company.name_local.len() > 34
    #block(below: 5pt, mk("1") + text(size: if long-name { 14pt } else { 17pt }, weight: "bold", fill: navy, vm.company.name)
      + if vm.company.name_local != "" { h(4pt) + text(size: if long-name { 10pt } else { 12pt }, fill: navy, vm.company.name_local) })
    #block(below: 4pt, text(size: 8pt, fill: muted)[
      *#vm.company.ticker* · #vm.company.exchange#if vm.company.sector != "" [ · #vm.company.sector]
    ])
    #if vm.company.description != "" {
      text(size: 6.9pt, fill: ink)[#vm.company.description]
    }
    #if "scorecard" in vm and vm.scorecard != none {
      v(1pt)
      block(above: 3pt)[
        #text(size: 5.8pt, weight: "bold", fill: navy, tracking: 0.06em)[SCORECARD] #h(3pt)
        #for a in vm.scorecard.areas {
          let f = if a.frac == none { 0 } else { a.frac }
          let col = if a.frac == none { rule-c } else if f >= 0.67 { pos-c } else if f >= 0.34 { rgb("#8A6D1F") } else { neg-c }
          box(inset: (right: 4pt))[
            #box(width: 14pt, height: 3.2pt, fill: rule-c, radius: 1pt, place(left, box(width: 14pt * f, height: 3.2pt, fill: col, radius: 1pt)))
            #h(1.5pt)#text(size: 6.3pt)[#a.short *#a.score*]
          ]
        }
        #if vm.scorecard.piotroski != "" { text(size: 6.3pt, fill: muted)[F-score *#vm.scorecard.piotroski*] }
      ]
    }
    #if "overall" in vm and vm.overall != none {
      let ov = vm.overall
      let chip(r) = box(fill: rating-col(r), inset: (x: 1.8pt, y: 0.8pt), radius: 1pt, text(size: 5.4pt, weight: "bold", fill: white, upper(r)))
      block(above: 5pt, width: 100%, stroke: (left: 2pt + rating-col(ov.rating)), inset: (left: 5pt, y: 1pt))[
        #mk("7")#box(fill: rating-col(ov.rating), inset: (x: 3.5pt, y: 1.8pt), radius: 1.5pt, text(size: 7pt, weight: "bold", fill: white, "OVERALL VIEW · " + upper(ov.rating)))
        #h(3pt) #text(size: 7pt)[*#ov.score* / 5] #h(3pt) #text(size: 5.8pt, fill: muted)[#ov.basis#if ov.range != "" [ · #ov.range]]#if ov.split != "" [ #h(2pt) #text(size: 6pt, fill: neg-c, weight: "bold", ov.split)]
        #v(-4pt)
        #text(size: 6.2pt)[#for (k, r) in ov.rows.enumerate() [#if k > 0 [#h(2pt)·#h(2pt)]#text(fill: muted, r.label) #chip(r.rating) #if r.strong != "" [*#r.strong* ]#r.text]]
        #if "debate" in vm and vm.debate != none {
          let dbt = vm.debate
          v(-4pt)
          text(size: 6.2pt)[#text(fill: muted)[AI debate] #text(weight: "bold", fill: if dbt.key == "bull" { pos-c } else if dbt.key == "bear" { neg-c } else { ink }, dbt.side) · #dbt.conviction#if dbt.alignment != "" [ · #dbt.alignment]]
        }
      ]
    } else if "street_line" in vm and vm.street_line != none {
      // the brokers' view on its own, beside ours: no blended score (round-4/5 reviews, user decision 9 Nov 2026)
      let sl = vm.street_line
      block(above: 5pt, width: 100%, stroke: (left: 2pt + rule-c), inset: (left: 5pt, y: 1pt))[
        // the data-only edition prints the brokers' counts without the one-word lean the code derives from them
        #mk("7")#box(fill: muted, inset: (x: 3.5pt, y: 1.8pt), radius: 1.5pt, text(size: 7pt, weight: "bold", fill: white, if data-only { "BROKER RATINGS" } else { "STREET VIEW · " + upper(sl.lean) }))
        #h(3pt) #text(size: 5.8pt, fill: muted)[(third-party views)] #h(2pt) #text(size: 6.2pt)[latest notes of #sl.n brokers: #sl.mix#if sl.target != "" [ · #sl.target].#if sl.ours != "" and not data-only [ #sl.ours.]]
        #if "debate" in vm and vm.debate != none {
          let dbt = vm.debate
          v(-4pt)
          text(size: 6.2pt)[#text(fill: muted)[AI debate] #text(weight: "bold", fill: if dbt.key == "bull" { pos-c } else if dbt.key == "bear" { neg-c } else { ink }, dbt.side) · #dbt.conviction#if dbt.alignment != "" [ · #dbt.alignment]]
        }
      ]
    }
  ],
  block(fill: navy-tint, inset: (x: 6pt, y: 5pt), radius: 2pt, width: 100%)[
    #set text(size: 7pt)
    #table(
      columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.6pt),
      ..vm.quote_items.map(it => (text(fill: muted, it.at(0)), strong(it.at(1)))).flatten()
    )
    #if "rating" in vm and vm.rating != none {
      let rt = vm.rating
      let col = if rt.rating == "Buy" { pos-c } else if rt.rating == "Sell" { neg-c } else if rt.rating == "Hold" { rgb("#8A6D1F") } else { muted }
      v(-1pt)
      line(length: 100%, stroke: 0.4pt + rule-c)
      v(-1pt)
      grid(columns: (auto, 1fr), column-gutter: 4pt, align: (left + horizon, right + horizon),
        [#mk("6")#box(fill: col, inset: (x: 3.5pt, y: 1.8pt), radius: 1.5pt, text(size: 7pt, weight: "bold", fill: white, "AI RATING · " + upper(rt.rating)))],
        if rt.rating != "Not rated" { text(size: 6.8pt)[Fair value *#rt.fair_value* #signed(rt.upside)] } else { text(size: 6pt, fill: muted)[methods disagree] })
    }
    #if "rating" in vm and vm.rating != none and vm.rating.at("buy_below", default: "") != "" {
      v(-3pt)
      text(size: 6pt)[#text(fill: pos-c)[Buy ≤ *#vm.rating.buy_below*] #h(2pt)·#h(2pt) #text(fill: neg-c)[Sell ≥ *#vm.rating.sell_above*]]
    }
    #v(-2pt)
    #text(size: 5.6pt, fill: muted)[Market data as of #vm.quote_asof]
  ],
)
#v(4pt)

// ---------- data-only edition: what this edition is (where the headline would be) ----------
#if data-only {
  block(width: 100%, above: 0pt, below: 4pt, stroke: (left: 2pt + navy), inset: (left: 6pt, y: 1.5pt))[
    #text(size: 6.7pt)[#text(weight: "bold", fill: navy, tracking: 0.04em)[DATA EDITION] #h(2pt) This edition has no AI-written text and no rating. Every figure comes from the sources listed and is calculated in code; the valuation figures are calculations from stated assumptions, not a recommendation. The boxes marked #text(weight: "bold", fill: navy)[Your analysis] are for your own view.]
  ]
}

// ---------- our view: headline + thesis (full width) ----------
#if vm.narrative != none and vm.narrative.at("tagline", default: "") != "" {
  block(width: 100%, above: 0pt, below: 4pt, stroke: (left: 2pt + navy), inset: (left: 6pt, y: 1.5pt))[
    #text(size: 8.4pt, weight: "bold", fill: navy, vm.narrative.tagline)
    #if vm.narrative.at("thesis", default: "") != "" {
      v(-2.5pt)
      par(justify: true, leading: 0.42em, text(size: 6.6pt, vm.narrative.thesis))
    }
  ]
}

#let view-section = section(mark: ("6",))[Valuation view][
  #if data-only { write-space(vm.ask.valuation) } else if has("comps") [
    #vm.narrative.comps
  ] else { status-note }
]

// ---------- performance + catalysts (valuation view under the chart, risks under the catalysts) ----------
#grid(
  columns: (1fr, 1fr),
  column-gutter: 10pt,
  section(mark: ("8",), if vm.chart != none [Relative performance · #vm.chart.period rebased to 100] else [Relative performance])[
    #if vm.chart != none {
      let c = vm.chart
      grid(columns: (auto, auto), column-gutter: 8pt,
        text(size: 6.3pt)[#box(width: 8pt, height: 1.4pt, fill: stock-c) #vm.company.ticker],
        text(size: 6.3pt)[#box(width: 8pt, height: 1.2pt, fill: bench-c) #c.bench_name])
      v(1pt)
      line-chart(c, 76mm, 24mm)
      v(2pt)
      table(
        columns: (auto, 1fr, 1fr, 1fr), stroke: none, inset: (x: 2pt, y: 1.4pt),
        align: (left, right, right, right),
        table.header(..([], [#vm.company.ticker], [#c.bench_name], [Relative]).map(h => text(fill: muted, size: 6.3pt, h))),
        table.hline(stroke: 0.4pt + rule-c),
        ..c.returns.map(r => (strong(r.at(0)), signed(r.at(1)), signed(r.at(2)), signed(r.at(3)))).flatten()
      )
    } else [
      #text(fill: muted)[Price history unavailable.]
    ]
    #view-section
  ],
  [
    // risks sit under the catalysts, beside the chart's return table (space that was empty), so the page-1 thesis
    // fits on one page
    #section[Key catalysts][
      #if data-only { write-space(vm.ask.catalysts) } else if has("catalysts") {
        for (i, b) in vm.narrative.catalysts.enumerate() { bullet(str(i + 1), b, navy) }
      } else { status-note }
    ]
    #section(mark: ("8",))[Key downside risks][
      #if data-only { write-space(vm.ask.risks) } else if has("risks") {
        for b in vm.narrative.risks { bullet("!", b, neg-c) }
      } else { status-note }
    ]
  ],
)
#v(3pt)

// ---------- 5-year financial summary ----------
#section(mark: ("2", "3", "4"))[5-year financial summary · #vm.fin.unit #if vm.fin.standard != "" [· #vm.fin.standard]][
  #let ny = vm.fin.years.len()
  #table(
    columns: (1.5fr,) + (1fr,) * ny + (0.9fr,),
    stroke: none,
    inset: (x: 3pt, y: 1.35pt),
    align: (left,) + (right,) * (ny + 1),
    fill: (_, row) => if row == 0 { navy } else if calc.even(row) { navy-tint } else { none },
    table.header(
      text(fill: white, weight: "bold")[Fiscal year],
      ..vm.fin.years.map(y => text(fill: white, weight: "bold", y)),
      text(fill: white, weight: "bold", vm.fin.cagr_label),
    ),
    ..vm.fin.rows.map(r => {
      let sty(s) = if r.style == "bold" { strong(s) } else if r.style == "sub" { text(fill: muted, size: 6.9pt, s) } else { s }
      (sty(r.label),) + r.values.map(v => sty(v)) + (sty(r.cagr),)
    }).flatten()
  )
]
#v(3pt)

// ---------- comps + DuPont ----------
#grid(
  columns: (1.62fr, 1fr),
  column-gutter: 10pt,
  section(mark: ("5",))[Comparable companies · relative valuation][
    #if vm.comps != none {
      let c = vm.comps
      table(
        columns: (1.75fr, 0.85fr, 0.95fr, 0.8fr, 0.8fr, 1fr, 0.75fr, 0.85fr),
        stroke: none, inset: (x: 2.2pt, y: 1.7pt),
        align: (left, left, right, right, right, right, right, right),
        table.header(..("Company", "Ticker", "Mkt cap", "P/E TTM", "P/E fwd", "EV/EBITDA", "P/B", "Div yld TTM")
          .map(h => text(fill: muted, size: 6.2pt, weight: "bold", h))),
        table.hline(stroke: 0.5pt + navy),
        table.cell(fill: navy-tint, strong(c.target.cells.at(0))),
        ..c.target.cells.slice(1).map(x => table.cell(fill: navy-tint, strong(x))),
        ..c.peers.map(r => r.cells).flatten(),
        table.hline(stroke: 0.4pt + rule-c),
        ..c.median.cells.map(x => strong(x)),
        ..c.premium.enumerate().map(((i, x)) => if i == 0 { text(size: 6.2pt, fill: muted, x) } else { text(size: 6.6pt, signed(x)) }),
      )
      v(-1pt)
      text(size: 5.8pt, fill: muted)[Market cap in #c.currency. #c.method]
    } else [
      #text(fill: muted)[Peer data unavailable for this listing.]
    ]
  ],
  section(mark: ("3",))[Return on equity · DuPont #if vm.dupont != none [(#vm.dupont.fy)]][
    #if vm.dupont != none {
      table(columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.5pt),
        ..vm.dupont.items.enumerate().map(((i, it)) => {
          let last = i == vm.dupont.items.len() - 1
          (if last { strong(it.at(0)) } else { it.at(0) }, if last { strong(it.at(1)) } else { it.at(1) })
        }).flatten())
    }
    #if vm.quality != none {
      v(-2pt)
      table(columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.5pt),
        ..vm.quality.map(it => (text(fill: muted, it.at(0)), it.at(1))).flatten())
    }
    #if has("dupont") {
      v(1pt)
      text(size: 7pt)[#vm.narrative.dupont]
    }
  ],
)
#v(3pt)

// ---------- intrinsic value + street view ----------
#let iv-section = if vm.valuation != none and vm.valuation.kind != none {
  let iv = vm.valuation
  section(mark: ("6",))[Intrinsic value · #iv.at("title", default: iv.kind + " (illustrative)")][
    #grid(
      columns: (1.05fr, 1fr),
      column-gutter: 8pt,
      table(columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.2pt),
        ..iv.wacc_rows.enumerate().map(((i, r)) => {
          let last = i == iv.wacc_rows.len() - 1 and iv.kind == "DCF"
          (if last { strong(r.at(0)) } else { text(fill: muted, r.at(0)) }, if last { strong(r.at(1)) } else { r.at(1) })
        }).flatten()),
      [
        #text(size: 6.4pt, fill: muted)[#iv.at("value_label", default: "Base-case value per share")] \
        #text(size: 11pt, weight: "bold", fill: navy, iv.value) #h(2pt) #signed(iv.upside) \
        #text(size: 6.2pt, fill: muted)[vs share price #iv.price]
      ],
    )
    #v(-2pt)
    #text(size: 6pt)[#iv.short_assumptions.map(a => text(fill: muted, a.at(0)) + " " + a.at(1)).join(" · ")]
  ]
} else { none }

#let street-section = if "street" in vm and vm.street != none {
  let st = vm.street
  section(mark: ("7",))[What brokers say · #st.source · third-party views][
    #table(columns: (auto, 1fr), stroke: none, inset: (x: 0pt, y: 1.1pt), column-gutter: 5pt,
      ..st.stats.map(r => (text(size: 6.3pt, fill: muted, r.at(0)), text(size: 6.4pt, r.at(1)))).flatten())
    #v(-1pt)
    #line(length: 100%, stroke: 0.3pt + rule-c)
    #v(-2pt)
    #for n in st.notes {
      block(below: 2.6pt, text(size: 6.3pt)[
        #text(fill: muted, n.date) #h(1pt) *#n.broker* #h(1pt)
        #if n.rating != "" { box(fill: rating-col(n.rating), inset: (x: 1.8pt, y: 0.8pt), radius: 1pt, text(size: 5.4pt, weight: "bold", fill: white, upper(n.rating))) }#n.target
        #if n.text != "" [ — #if n.translated { n.text } else { text(fill: ink, n.text) }]
      ])
    }
  ]
} else { none }

#if iv-section != none or street-section != none {
  if iv-section != none and street-section != none {
    grid(columns: (1fr, 1fr), column-gutter: 10pt, iv-section, street-section)
  } else if iv-section != none { iv-section } else { street-section }
}
#if vm.narrative != none and vm.narrative.status == "flagged" { v(2pt); status-note }

// ---------- footer ----------
// The learner guide prints these notes on its last page instead: its annotated tear sheet is full, and the footer
// spilled onto an empty page of its own (round-4 review: "a blank page").
#if not learner-layout [
#v(1fr)
#line(length: 100%, stroke: 0.5pt + rule-c)
#set text(size: 5.6pt, fill: muted)
#if vm.footer.warnings.len() > 0 [
  *Data notes:* #vm.footer.warnings.join(" · ") \
]
// One line, not two: in the learner layout a second line pushed the footer onto a page of its own (round-4 review).
// "Matched to the data in code", not "verified": the check finds each number in the data, it does not prove each statement.
#if learner-layout [*Sources:* listed in the full research report.] else [*Sources:* #vm.footer.sources.] *Generated* #vm.footer.generated by InvestSync Research Tools#if vm.narrative != none and vm.narrative.model != "" [; AI commentary by #vm.narrative.model, its figures matched to the data in code].#if sys.inputs.at("layout", default: "tearsheet") != "tearsheet" [ Not investment advice; full disclaimer: #if learner-layout [page 1] else [last chapter].]
#if sys.inputs.at("layout", default: "tearsheet") == "tearsheet" [
  #v(1pt)
  #vm.footer.disclaimer
]
]
