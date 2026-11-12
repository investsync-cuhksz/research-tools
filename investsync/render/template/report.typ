// InvestSync Research Tools: full equity research report.
// Page 1 is the one-page tear sheet (tearsheet.typ); chapters 1-11 follow.
// Data: view-model JSON from investsync/render/viewmodel.py + report_vm.py.

#import "lib.typ": *

#let vm = json(sys.inputs.at("data"))
#let r = vm.report
#let ai = r.ai
#let co = vm.company
// the data-only edition (12 Nov 2026): no AI text, no rating; "Your analysis" boxes (lib.typ write-box)
#let data-only = r.at("data_only", default: false)

#set document(title: co.name + " (" + co.ticker + ") · InvestSync " + if data-only { "Equity Research Data Edition" } else { "Equity Research Report" },
              author: "InvestSync Research Tools")

#include "tearsheet.typ"
#set text(font: ("Inter", "Helvetica Neue", "Helvetica", "Arial", "PingFang SC", "Hiragino Sans GB", "STHeiti", "Noto Sans CJK SC", "Noto Sans SC"),
          size: 7.4pt, fill: ink, lang: "en")
#set par(leading: 0.5em, spacing: 0.75em, justify: false)
#set page(
  paper: "a4",
  margin: (x: 12mm, top: 15mm, bottom: 13mm),
  header: context [
    #grid(columns: (auto, 1fr), align: (left + horizon, right + horizon),
      image("../assets/investsync-logo.png", height: 5.2mm),
      text(size: 6.2pt, fill: muted)[*#co.name* · #co.ticker · #if data-only [Data edition: no AI text, no rating] else [Equity research report] · #vm.date])
    #v(-3pt)
    #line(length: 100%, stroke: 0.6pt + navy)
  ],
  footer: context [
    #line(length: 100%, stroke: 0.4pt + rule-c)
    #v(-3pt)
    #grid(columns: (1fr, auto),
      text(size: 5.6pt, fill: muted)[InvestSync Research Tools · for education within the InvestSync Student Investment Organization (CUHK-Shenzhen) · not investment advice],
      text(size: 6pt, fill: muted, counter(page).display("1 / 1", both: true)))
  ],
)

#let col2(a, b, ratio: (1fr, 1fr), gutter: 12pt) = grid(columns: ratio, column-gutter: gutter, a, b)
#let cites = r.citations
// Source references go under the chapter title: at the chapter end, a full last page pushed them onto a page of
// their own (round-4 review: "page 20 is blank").
#let src(key) = if cites.refs.at(key, default: "") != "" { small-note(cites.refs.at(key)) }
#let na(what) = text(fill: muted, size: 6.6pt)[#what not available for this listing.]

// =====================================================================================
// 1 · Summary and data audit
// =====================================================================================
#chapter(r.num.summary, "Investment summary", sub: "key figures, valuation range and data checks")
#src("summary")

#if ai.tagline.value != none {
  block(below: 6pt, text(size: 10pt, weight: "bold", fill: navy, ai.tagline.value))
}

#grid(columns: (1fr,) * 4, column-gutter: 5pt, row-gutter: 5pt,
  ..r.summary.tiles.map(t => block(width: 100%, fill: navy-tint, radius: 2pt, inset: (x: 6pt, y: 5pt))[
    #text(size: 5.8pt, fill: muted, tracking: 0.05em, upper(t.at(0))) \
    #text(size: 10pt, weight: "bold", fill: navy, t.at(1))
  ]))

#if r.overall != none {
  let ov = r.overall
  section("Overall view", note: "the InvestSync model and every broker's latest recent view, combined in code")[
    #grid(columns: (0.95fr, 1.6fr), column-gutter: 12pt, [
      #block(fill: navy-tint, radius: 2pt, inset: 7pt, width: 100%)[
        #rating-badge(ov.rating) #h(4pt) #text(size: 12pt, weight: "bold", fill: navy)[#ov.score] #text(size: 7pt, fill: muted, "/ 5") \
        #v(2pt)
        #text(size: 6.4pt, fill: muted)[#ov.basis] \
        #if ov.targets != "" { text(size: 6.4pt)[#ov.targets] }
        #if ov.split != "" { v(2pt); text(size: 6.2pt, fill: neg-c)[#ov.split] }
      ]
    ], [
      #table(columns: (1.25fr, auto, auto, auto, 2fr), stroke: none, inset: (x: 2.5pt, y: 1.7pt), align: (left, left, right, right, left),
        table.header(..([Input], [View], [Score], [Weight], [Detail]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.4pt + rule-c),
        ..ov.rows.map(x => (text(size: 6.4pt, weight: "bold", x.at(0)), text(size: 6.4pt, weight: "bold", fill: rating-colour(x.at(1)), x.at(1)),
          text(size: 6.4pt, x.at(2)), text(size: 6.4pt, x.at(3)), text(size: 6.1pt, x.at(4)))).flatten())
      #if ov.votes != "" { small-note[*Broker views counted* (latest per broker): #ov.votes] }
      #if ov.stale != "" { small-note[*Left out as out of date* (latest view older than the window): #ov.stale] }
      #small-note[#ov.method]
    ])
  ]
}

#if r.summary.rating != none {
  let rt = r.summary.rating
  section("AI rating", note: rt.at("note", default: "set by a fixed rule from the valuation below; the AI only explains it"))[
    #grid(columns: (0.95fr, 1.6fr), column-gutter: 12pt, [
      #block(fill: navy-tint, radius: 2pt, inset: 7pt, width: 100%)[
        #rating-badge(rt.rating)
        #if rt.rating != "Not rated" [
          #h(5pt) #text(size: 7pt, fill: muted)[#rt.confidence confidence] \
          #v(3pt)
          #text(size: 6.4pt, fill: muted)[#rt.at("fv_label", default: "Fair value (blended)")] \
          #text(size: 12pt, weight: "bold", fill: navy, rt.fair_value) #h(3pt) #signed(rt.upside) \
          #text(size: 6.4pt, fill: muted)[vs share price #rt.price]
        ] else [
          \ #v(2pt) #text(size: 6.6pt, fill: muted, rt.reason)
        ]
        #if rt.buy_below != "" {
          v(1pt)
          text(size: 6.4pt)[#text(fill: pos-c)[Buy at or below *#rt.buy_below*] \ #text(fill: neg-c)[Sell at or above *#rt.sell_above*]]
        }
        #v(1pt)
        #text(size: 5.8pt, fill: muted)[#rt.rule Generated mechanically for education; not investment advice.]
      ]
      #if r.since_last != none {
        let sl = r.since_last
        block(above: 4pt, width: 100%, inset: (x: 6pt, y: 4pt), radius: 2pt, stroke: 0.5pt + rule-c)[
          #text(size: 6.2pt, weight: "bold", fill: navy)[Since the last report (#sl.date)]#if sl.since != "" [ #h(2pt) #chip(sl.since, fill: rating-colour(vm.rating.rating))] \
          #text(size: 6.2pt)[#sl.changes.join(" ")]
        ]
      }
    ], [
      #if rt.methods.len() > 0 {
        table(columns: (1.5fr, 1fr, auto, 1.3fr), stroke: none, inset: (x: 2.5pt, y: 1.7pt), align: (left, right, right, left),
          table.header(..([Method], [Value per share], [Weight], [#if rt.at("cross_check", default: false) [Role] else [Status]]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
          table.hline(stroke: 0.4pt + rule-c),
          ..rt.methods.map(m => (text(size: 6.5pt, m.at(0)), text(size: 6.5pt, m.at(1)), text(size: 6.5pt, m.at(2)),
            text(size: 6.2pt, fill: if m.at(3) == "used" or m.at(3).starts-with("cross-check") { ink } else { neg-c }, m.at(3)))).flatten())
      }
      #v(2pt)
      #ai-box(ai.rating_rationale, status: ai.status)
      #v(2pt)
      #table(columns: (auto, 1fr), stroke: none, inset: (x: 2.5pt, y: 1.4pt),
        table.header(text(size: 5.8pt, fill: muted, weight: "bold")[Rating], text(size: 5.8pt, fill: muted, weight: "bold")[Definition (house thresholds)]),
        table.hline(stroke: 0.4pt + rule-c),
        ..rt.definitions.map(d => (text(size: 6.2pt, weight: "bold", fill: rating-colour(d.at(0)), d.at(0)), text(size: 6.2pt, d.at(1)))).flatten())
      #if rt.at("risks_fv", default: "") != "" [#v(2pt) #text(size: 6.3pt)[*Risks to our fair value.* #rt.risks_fv]]
    ])
  ]
}

#section(if data-only { "Your investment case" } else { "Investment thesis" }, note: if data-only { "this edition has no AI text and no rating: write your own view here" } else { none })[
  #col2(ai-box(ai.thesis, status: ai.status), ai-box(ai.key_takeaways, status: ai.status), ratio: (1.35fr, 1fr))
]

// run 2: the lead analyst's pillars, each with its evidence and what would prove it wrong (the brief's own text,
// figures re-checked in code); omitted when the brief is missing or does not parse
#let pl = r.at("pillars", default: none)
#if pl != none {
  section("What our view rests on", note: "the lead analyst's thesis pillars · each says what would prove it wrong")[
    #if pl.question != "" { block(below: 4pt, text(size: 7.2pt)[#text(weight: "bold", fill: navy)[The question:] #pl.question]) }
    #table(columns: (auto, 1.05fr, 1.55fr, 1.2fr), stroke: none, inset: (x: 2.5pt, y: 2pt),
      align: (left, left, left, left),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..([], [Pillar], [Evidence], [What would break it]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..pl.rows.enumerate().map(((i, x)) => (text(size: 6.6pt, weight: "bold", fill: navy, str(i + 1)),
        text(size: 6.6pt, weight: "bold", x.at(0)), text(size: 6.4pt, x.at(1)), text(size: 6.4pt, x.at(2)))).flatten())
  ]
}

// run 4: the year the valuation rests on and what will decide it (the judgement model's drivers, checked in code)
#let dy = r.at("deciding", default: none)
#if dy != none {
  section("What decides " + dy.period, note: dy.note)[
    #table(columns: (1fr, 2.6fr, auto), stroke: none, inset: (x: 2.5pt, y: 2pt),
      align: (left, left, left),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..([Driver], [Evidence], [For our base case]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..dy.rows.map(x => (text(size: 6.6pt, weight: "bold", x.at(0)), text(size: 6.4pt, x.at(1)),
        text(size: 6.4pt, weight: "bold", fill: if x.at(2) == "Supports" { navy } else if x.at(2) == "At risk" { rgb("#B4430A") } else { muted }, x.at(2)))).flatten())
    #if dy.verdict != "" { block(above: 3pt, text(size: 6.6pt)[#text(weight: "bold", fill: navy)[Verdict:] #dy.verdict]) }
  ]
}

#section(if data-only { "Valuation ranges" } else { "Valuation summary" }, note: "value per share from each method, " + vm.quote_items.at(0).at(1).split(" ").at(0) + if data-only { " · calculations, not a recommendation" } else { "" })[
  #if r.summary.football != none {
    fit(w => football(r.summary.football, w))
  } else { na("Valuation ranges") }
]

#if r.summary.football != none and data-only {
  small-note[Bars show each method's range; the black tick marks its central value and the red line today's price. Peer-multiple bars apply the peers' 25th–75th percentile multiple to the company's own earnings, EBITDA or book value. Analyst targets are third-party consensus, shown for context. Each bar is a calculation from the data, not a recommendation; chapter #r.num.valuation shows the workings.]
} else if r.summary.football != none {
  small-note[Bars show each method's range; the black tick marks its central value and the red line today's price. Peer-multiple bars apply the peers' 25th–75th percentile multiple to the company's own earnings, EBITDA or book value. The dashed line is the blended fair value behind the AI rating. Analyst targets are third-party consensus, shown for context only, and never enter the rating.]
}


#section("Data audit", note: "automatic checks run on every report")[
  #if r.summary.audit != none {
    let a = r.summary.audit
    // the audit reports what code checked; it never certifies the report (round-4 review: "✓ PUBLISHABLE" read as an overclaim)
    let badge = if a.status == "publishable" { chip("✓ data checks passed", fill: st-good) } else if a.status == "caveated" { chip("! data checks: see notes", fill: st-warn, fg: ink) } else { chip("✕ data checks failed", fill: st-crit) }
    block(below: 4pt)[#badge #h(4pt) #text(size: 6.6pt, fill: muted)[#a.checks.filter(c => c.status == "pass").len() of #a.checks.len() automatic checks passed · they test the data and the figures, not the judgements]]
    table(columns: (auto, 1.1fr, 3.2fr), stroke: none, inset: (x: 3pt, y: 2pt), align: (left + horizon, left + horizon, left + horizon),
      fill: (_, row) => if calc.odd(row) { navy-tint } else { none },
      ..a.checks.map(c => (status-chip(c.status), text(weight: "bold", c.name), text(size: 6.6pt, c.detail))).flatten())
  }
]

// 12 Nov 2026: questions an analyst would ask (config/question_bank.json + AI-added ones from recent evidence).
// Standard report: the reader's homework; deep report: answered; data-only edition: with lines to write on.
#let aq = r.at("questions", default: none)
#if aq != none and aq.rows.len() > 0 {
  let new-chip = chip("NEW", fill: ai-c)
  let qcell(q) = [
    #text(size: 6.7pt, weight: "bold", q.text)
    #if q.why != "" [ \ #text(size: 6.1pt, fill: muted)[_Why now:_ #q.why]]
  ]
  section(aq.title, note: aq.note, breakable: true)[
    #if data-only {
      for q in aq.rows {
        block(width: 100%, breakable: false, above: 5pt, below: 2pt)[
          #text(size: 6.9pt)[#text(weight: "bold", fill: navy, q.n + ".") #h(2pt) *#q.text*] \
          #text(size: 6.1pt, fill: muted)[#q.theme#if q.data != "" [ · *Our data:* #q.data]#if q.where != "" [ · *Where to look:* #q.where]]
          #for i in range(aq.lines) { block(above: 11pt, below: 0pt, line(length: 100%, stroke: (paint: rule-c, thickness: 0.6pt, dash: "dotted"))) }
        ]
      }
    } else if aq.answers {
      table(columns: (auto, 1.7fr, 2fr), stroke: none, inset: (x: 2.5pt, y: 2.2pt), align: (left, left, left),
        fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
        table.header(..([], [Question], [Answer]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.5pt + navy),
        ..aq.rows.map(q => (
          text(size: 6.6pt, weight: "bold", fill: navy, q.n),
          [#text(size: 5.9pt, weight: "bold", fill: muted, upper(q.theme)) #if q.new { new-chip } \ #qcell(q)
           #if q.data != "" [ \ #text(size: 6pt)[*Our data:* #q.data]]],
          if q.open {
            [#chip("OPEN", fill: muted) #h(2pt) #text(size: 6.5pt, if q.answer != "" { q.answer } else { aq.open_text })]
          } else { text(size: 6.5pt, q.answer) },
        )).flatten())
    } else {
      table(columns: (auto, 0.62fr, 2.5fr, 1.75fr, 0.72fr), stroke: none, inset: (x: 2.5pt, y: 2pt),
        align: (left, left, left, left, left),
        fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
        table.header(..([], [Theme], [Question], [Our data (computed in code)], [Where to look]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.5pt + navy),
        ..aq.rows.map(q => (
          text(size: 6.6pt, weight: "bold", fill: navy, q.n),
          [#text(size: 6.1pt, weight: "bold", fill: muted, q.theme) #if q.new [ \ #new-chip]],
          qcell(q),
          text(size: 6.1pt, if q.data != "" { q.data } else { "–" }),
          text(size: 5.9pt, fill: muted, q.where),
        )).flatten())
    }
  ]
}

// =====================================================================================
// Deep mode · Investment debate (analyst -> bull / bear -> rebuttals -> judge -> reviewer)
// =====================================================================================
#if r.at("deep", default: none) != none {
  let dp = r.deep
  let vd = dp.verdict
  let side-col(k) = if k == "bull" { pos-c } else if k == "bear" { neg-c } else { muted }
  let stance-col(k) = if k == "bull" or k == "positive" { pos-c } else if k == "bear" or k == "negative" { neg-c } else { muted }
  let refs(rs) = if rs.len() > 0 {
    block(above: 2pt, text(size: 5.9pt, fill: muted)[#for (i, e) in rs.enumerate() [#if i > 0 [ · ]#text(weight: "bold", fill: stance-col(e.stance), e.id) #e.label#if e.value != "" [: #e.value]]])
  }
  let argument(a, col) = block(width: 100%, breakable: false, below: 6pt, inset: (left: 5pt), stroke: (left: 1.2pt + col))[
    #text(size: 7pt)[#text(weight: "bold", fill: col, a.id) #h(2pt) *#a.claim*] \
    #text(size: 6.7pt, a.reasoning) \
    #text(size: 6.2pt)[#text(fill: muted)[Assumption:] #a.assumption #h(3pt) #text(fill: muted)[Breaks if:] #a.breaks_if]
    #refs(a.refs)
  ]
  pagebreak(weak: true)
  chapter(r.num.debate, "Investment debate", sub: "analyst findings, bull vs bear and the judge's verdict · AI analysis, every figure checked in code")
  block(width: 100%, fill: ai-tint, inset: (x: 7pt, y: 6pt), radius: 2pt, stroke: (left: 2pt + side-col(vd.key)), below: 8pt)[
    #chip("JUDGE", fill: ai-c) #h(3pt) #text(size: 9pt, weight: "bold", fill: side-col(vd.key), vd.side) #h(4pt) #chip(upper(vd.conviction) + " CONVICTION", fill: muted)
    #v(1pt)
    #par(justify: true, text(size: 7.2pt, vd.text))
    #grid(columns: (1fr, 1fr), column-gutter: 10pt,
      [#text(size: 6.6pt, weight: "bold", fill: navy)[Swing factor] \ #text(size: 6.8pt, vd.swing)],
      [#text(size: 6.6pt, weight: "bold", fill: navy)[What would change the view] \ #text(size: 6.8pt, vd.change)])
    #v(1pt)
    #text(size: 6.3pt, fill: muted, vd.alignment)
  ]
  col2(
    section("Bull case", note: str(dp.bull.len()) + " argument" + (if dp.bull.len() != 1 { "s" } else { "" }) + " after the evidence checks")[
      #if dp.bull.len() == 0 { text(size: 6.6pt, fill: muted)[No bull argument survived the evidence checks.] }
      #for a in dp.bull { argument(a, pos-c) }
    ],
    section("Bear case", note: str(dp.bear.len()) + " argument" + (if dp.bear.len() != 1 { "s" } else { "" }) + " after the evidence checks")[
      #if dp.bear.len() == 0 { text(size: 6.6pt, fill: muted)[No bear argument survived the evidence checks.] }
      #for a in dp.bear { argument(a, neg-c) }
    ],
  )
  if dp.rebuttals.len() > 0 or dp.concessions.len() > 0 or vd.divergences.len() > 0 {
    col2(
      section("Rebuttals and concessions")[
        #set text(size: 6.6pt)
        #for rb in dp.rebuttals [- *#rb.side on #rb.target:* #rb.response]
        #for c in dp.concessions [- #text(fill: muted)[#c.at(0) concedes:] #c.at(1)]
      ],
      section("Where the two sides differ", note: "judge")[
        #set text(size: 6.6pt)
        #for d in vd.divergences [- #d]
      ],
    )
  }
  col2(ratio: (1.45fr, 1fr),
    section("Analyst findings", note: "each cites the evidence below", breakable: true)[
      #table(columns: (auto, 1fr, auto), stroke: none, inset: (x: 2pt, y: 1.6pt), align: (left, left, left),
        fill: (_, row) => if calc.odd(row) { navy-tint } else { none },
        ..dp.findings.map(f => (text(size: 6.2pt, weight: "bold", f.area), text(size: 6.4pt, f.finding), text(size: 5.8pt, fill: stance-col(f.stance), f.ids))).flatten())
    ],
    [
      #section("What the price implies")[#par(justify: true, text(size: 6.8pt, dp.priced_in))]
      #if dp.questions.len() > 0 { section("Questions that decide the case")[#set text(size: 6.7pt); #for (i, q) in dp.questions.enumerate() [#(i + 1). #q \ ]] }
    ],
  )
  if dp.at("scenarios", default: none) != none {
    let sc = dp.scenarios
    section("Scenarios", note: "AI assumptions, values computed in code with the model's DCF")[
      #table(columns: (auto, auto, auto, auto, auto, auto, 1fr), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
        align: (left, right, right, right, right, right, left),
        fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
        table.header(..([Scenario], [Prob.], [Revenue growth, next 3 yrs], [FCF margin], [Value / share], [vs price], [Drivers]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.5pt + navy),
        ..sc.rows.map(x => (text(size: 6.6pt, weight: "bold", x.at(0)), text(size: 6.6pt, x.at(1)), text(size: 6.4pt, x.at(2)), text(size: 6.6pt, x.at(3)), text(size: 6.6pt, weight: "bold", x.at(4)), text(size: 6.6pt, signed(x.at(5))), text(size: 6.2pt, x.at(6)))).flatten(),
        table.hline(stroke: 0.4pt + rule-c),
        text(size: 6.6pt, weight: "bold")[Weighted], [], [], [], text(size: 6.6pt, weight: "bold", sc.weighted), text(size: 6.6pt, weight: "bold", signed(sc.weighted_upside)), [])
      #small-note(sc.note)
      #if sc.at("bridge", default: ()).len() > 0 {
        v(3pt)
        text(size: 6.4pt, weight: "bold", fill: navy)[From the model DCF to our fair value]
        h(4pt)
        text(size: 6pt, fill: muted)[each step changes one input; the steps add up]
        v(-2pt)
        box(width: 62%, kv(sc.bridge, size: 6.5pt, bold-last: true))
      }
    ]
  }
  // run 2: deep-only exhibits from the scenario model, each omitted when it could not be built
  let sm = dp.at("model", default: none)
  if sm != none {
    section("Scenario model", note: "revenue paths and where each scenario's value comes from · computed in code")[
      #year-table(sm.years, sm.growth, label: "Revenue growth", label-col: 1.3fr)
      #v(3pt)
      #table(columns: (auto, auto, 1.1fr, 1.1fr, 1.1fr, auto, auto, auto), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
        align: (left,) + (right,) * 7,
        table.header(..sm.head.map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.5pt + navy),
        ..sm.summary.map(x => (text(size: 6.6pt, weight: "bold", x.at(0)),) + x.slice(1, 6).map(y => text(size: 6.6pt, y))
          + (text(size: 6.6pt, weight: "bold", x.at(6)), text(size: 6.6pt, signed(x.at(7))))).flatten())
      #small-note(sm.note)
    ]
  }
  let fr = dp.at("flip", default: none)
  if fr != none {
    section("Where the rating flips", note: "fair value per share (" + fr.currency + ") under other scenario weights · computed in code")[
      #let tint(rt) = if rt == "Buy" { pos-c.lighten(86%) } else if rt == "Sell" { neg-c.lighten(86%) } else { none }
      #box(width: 78%, table(columns: (auto,) + (1fr,) * fr.cols.len(), stroke: none, inset: (x: 2.5pt, y: 2.2pt),
        align: (left,) + (center,) * fr.cols.len(),
        table.header(text(size: 5.8pt, fill: muted)[Bear prob. ↓ / bull prob. →], ..fr.cols.map(c => text(size: 6.2pt, weight: "bold", fill: muted, c))),
        table.hline(stroke: 0.4pt + rule-c),
        ..fr.rows.map(rw => (text(size: 6.4pt, weight: "bold", fill: muted, rw.label),) + rw.cells.map(c => table.cell(
          fill: tint(c.rating), stroke: if c.current { 1pt + navy } else { none },
          text(size: 6.5pt, weight: if c.current { "bold" } else { "regular" })[#c.text #text(size: 5.6pt, weight: "bold", fill: rating-colour(c.rating), c.rating)]))).flatten()))
      #small-note(fr.note)
    ]
  }
  col2(
    section("Variant view", note: "vs the brokers")[#par(justify: true, text(size: 6.8pt, dp.variant))],
    section("Pre-mortem", note: "if the case fails in 12 months")[#par(justify: true, text(size: 6.8pt, dp.pre_mortem))],
  )
  // the review log (final run, 10 Nov 2026: the brief asks for one). Only the issues fixed or removed before
  // publication are printed (round-7 review: an "open" item read as an unfinished document); the rest stays in JSON
  let done = dp.review.filter(x => x.status != "open")
  if done.len() > 0 {
    section("Review log", note: "issues the reviewer raised on the draft, and how each was fixed", breakable: true)[
      #table(columns: (auto, 1fr, 1.25fr), stroke: none, inset: (x: 2pt, y: 1.6pt), align: (left, left, left),
        fill: (_, row) => if row == 0 { none } else if calc.odd(row) { navy-tint } else { none },
        text(size: 6pt, weight: "bold", fill: muted)[Section], text(size: 6pt, weight: "bold", fill: muted)[Issue],
        text(size: 6pt, weight: "bold", fill: muted)[How it was fixed],
        ..done.map(x => (text(size: 6.2pt, weight: "bold", x.section.replace("_", " ")),
                         text(size: 6.3pt)[#x.problem: "#x.quote"],
                         text(size: 6.3pt, if x.status == "removed" [Removed from the text.] else [#x.fix]))).flatten())
    ]
  }
  small-note(dp.at("review_line", default: "") + " " + dp.method)

}

// =====================================================================================
// 3 · Company overview
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.overview, "Company overview")
#src("overview")

#col2(ratio: (1.55fr, 1fr), [
  // round 8: the data vendor's boilerplate profile was called padding; it is shown only when there is no AI overview
  #if ai.company_overview.at("value", default: none) in (none, "") {
    section("Business description")[
      #par(justify: true, text(size: 7.2pt, r.overview.description))
    ]
    v(2pt)
  }
  #ai-box(ai.company_overview, status: ai.status)
], [
  #section("Company facts")[
    #kv(r.overview.facts, size: 6.8pt, columns: (auto, 1fr))  // long values wrap instead of squeezing the labels
    #if r.overview.sources != "" { small-note[Source: #r.overview.sources] }
  ]
])

#section("Revenue breakdown", note: if r.overview.segments.len() > 0 { "latest annual report · " + r.overview.segments.at(0).period + " · " + r.overview.segments.at(0).source } else { none })[
  #if r.overview.segments.len() > 0 {
    grid(columns: (1fr,) * r.overview.segments.len(), column-gutter: 14pt,
      ..r.overview.segments.map(s => [
        #chart-title(s.title + " · share of revenue")
        #fit(w => hbars(s.items.map(it => (label: it.name, frac: it.frac, text: it.share)), w, label-w: 92pt, value-w: 30pt))
        #v(2pt)
        #table(columns: (1fr, auto, auto) + if s.has_gm { (auto,) } else { () }, stroke: none, inset: (x: 2pt, y: 1.3pt),
          align: (left, right, right, right),
          table.header(..(([Segment], [Revenue (#s.currency)], [Share]) + if s.has_gm { ([Gross margin],) } else { () }).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
          table.hline(stroke: 0.4pt + rule-c),
          ..s.items.map(it => (text(size: 6.4pt, it.name), text(size: 6.4pt, it.revenue), text(size: 6.4pt, it.share)) + if s.has_gm { (text(size: 6.4pt, it.gm),) } else { () }).flatten())
      ]))
    small-note[Segment names as published (Chinese sources are shown in the original where no standard translation exists).]
  } else { na("A revenue breakdown") }
]


// =====================================================================================
// 3 · Financial analysis
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.financials, "Financial analysis", sub: vm.fin.standard + " · five fiscal years and the latest reported period")
#src("financials")

#let fa = r.financials
#let lv = fa.at("latest", default: none)
#let period-table(head, rows) = table(
  columns: (1.7fr, 1fr, 1fr, 0.75fr), stroke: none, inset: (x: 3pt, y: 1.55pt),
  align: (left, right, right, right),
  table.header(..head.map(x => text(fill: white, weight: "bold", x))),
  fill: (_, row) => if row == 0 { navy } else if calc.even(row) { navy-tint } else { none },
  ..rows.map(rw => rw).flatten(),
)
#if lv != none {
  section("Latest reported period · " + lv.label + " vs " + lv.prior_label, note: lv.unit + " · to " + lv.period_end)[
    #if lv.quarter != none {
      col2(ratio: (1fr, 1fr), period-table(("Year to date", lv.label, lv.prior_label, "Change"), lv.rows),
           period-table(("Latest quarter", lv.quarter.label, "a year earlier", "Change"), lv.quarter.rows))
    } else {
      period-table(("Year to date", lv.label, lv.prior_label, "Change"), lv.rows)
    }
    #if lv.balance.len() > 0 { small-note("Balance sheet at " + lv.period_end + ": " + lv.balance.map(b => b.at(0) + " " + b.at(1)).join("; ") + ".") }
    #if lv.ttm != none and lv.ttm.len() > 0 { small-note("Trailing twelve months (" + lv.ttm_basis + "): " + lv.ttm.map(b => b.at(0) + " " + b.at(1)).join("; ") + ".") }
    #if lv.capex_note != none { small-note(lv.capex_note) }
  ]
  v(4pt)
}
#grid(columns: (1fr, 1fr), column-gutter: 14pt, row-gutter: 10pt,
  ..fa.charts.map(c => [
    #chart-title(c.title)
    #legend(c.legend)
    #if "cats" in c and "series" in c and c.series.len() > 0 and "bars" in c.series.at(0) { fit(w => bar-chart(c, w, 44mm)) } else { fit(w => line-chart(c, w, 44mm)) }
  ]))

#col2(ratio: (1fr, 1.25fr), [
  #section("Earnings per share")[
    #if fa.eps != none { fit(w => bar-chart(fa.eps, w, 38mm)); v(1pt); small-note(fa.eps.title) } else { na("EPS history") }
  ]
], [
  #section("Return on equity · DuPont decomposition", note: "average balances")[
    #year-table(fa.years, fa.dupont, label: "")
    #small-note[ROE = net margin × asset turnover × equity multiplier. Cash conversion above 1.0x and a negative accruals ratio mean profits are backed by cash.]
  ]
])

#v(2pt)
#ai-box(ai.financial_analysis, status: ai.status)

// =====================================================================================
// 4 · Financial statements
// =====================================================================================
#pagebreak(weak: true)
#let st = r.statements
#chapter(r.num.statements, "Financial statements", sub: st.unit + " unless stated · " + st.standard)
#src("financials")

#section("Income statement")[ #year-table(st.years, st.income, label: "Fiscal year") ]
#section("Balance sheet")[ #year-table(st.years, st.balance, label: "Fiscal year") ]
#section("Cash flow")[ #year-table(st.years, st.cash, label: "Fiscal year") ]
#small-note[Costs, capex, dividends and buybacks shown as negatives. Debt excludes lease liabilities.]
#section("Key ratios")[
  #let ny = st.years.len()
  #table(
    columns: (1.9fr,) + (1fr,) * ny, stroke: none, inset: (x: 3pt, y: 1.55pt),
    align: (left,) + (right,) * ny,
    table.header(text(fill: white, weight: "bold")[Ratio], ..st.years.map(y => text(fill: white, weight: "bold", y))),
    fill: (_, row) => if row == 0 { navy } else { none },
    ..st.ratios.map(g => (
      table.cell(colspan: ny + 1, fill: navy-tint, text(size: 6.4pt, weight: "bold", fill: navy, upper(g.group))),
      ..g.rows.map(rw => (rw.label,) + rw.values.map(x => signed(x))).flatten(),
    )).flatten()
  )
]

// =====================================================================================
// 5 · Valuation
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.valuation, "Valuation", sub: "intrinsic value, sensitivities, market-implied expectations and multiples")
#src("valuation")
#if data-only { small-note[Every value in this chapter is a calculation from the data and the assumptions stated with it (and the brokers' figures are third-party views). None is a recommendation or a price target: change an assumption in the Excel data pack's model sheet to see how the value moves.] }

#let fc = r.at("forecast", default: none)
#if fc != none {
  section("Our forecast", note: "drivers set by the AI analyst, figures computed in code · consensus alongside", breakable: true)[
    #year-table(fc.years, fc.rows, label: "Forecast year")
    #table(columns: (auto, 1fr), stroke: none, inset: (x: 2pt, y: 1.6pt),
      ..fc.drivers.map(x => (text(size: 6.2pt, weight: "bold", x.at(0)), text(size: 6.4pt, x.at(1)))).flatten())
    #small-note(fc.note)
  ]
}
#let pv = r.at("preview", default: none)
#if pv != none {
  section(pv.title, note: "consensus for the next two quarters" + if pv.ours != "" { ", and what our forecast implies" } else { "" })[
    #table(columns: (auto, auto, auto, auto, auto, auto), stroke: none, inset: (x: 2.5pt, y: 1.7pt),
      align: (left, right, right, right, right, right),
      table.header(..([Quarter], [#pv.rev_head], [y/y], [EPS (consensus)], [y/y], [Analysts]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.4pt + rule-c),
      ..pv.rows.map(x => x.map(y => text(size: 6.5pt, y))).flatten())
    #if pv.ours != "" [#text(size: 6.6pt)[*Our forecast:* #pv.ours]]
    #if pv.at("options", default: "") != "" [ \ #text(size: 6.6pt)[*What the market prices:* #pv.options]]
    #small-note(pv.note)
  ]
}
#let asc = r.at("analyst_scenarios", default: none)
#if asc != none and (r.deep == none or r.deep.at("scenarios", default: none) == none) {
  section("Scenarios", note: "bear / base / bull · base case = our forecast · values computed in code with the model's DCF")[
    #table(columns: (auto, auto, auto, auto, auto, auto, 1fr), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
      align: (left, right, right, right, right, right, left),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..([Scenario], [Prob.], [Revenue growth, next 3 yrs], [FCF margin], [Value / share], [vs price], [Drivers]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..asc.rows.map(x => (text(size: 6.6pt, weight: "bold", x.at(0)), text(size: 6.6pt, x.at(1)), text(size: 6.4pt, x.at(2)), text(size: 6.6pt, x.at(3)), text(size: 6.6pt, weight: "bold", x.at(4)), text(size: 6.6pt, signed(x.at(5))), text(size: 6.2pt, x.at(6)))).flatten(),
      table.hline(stroke: 0.4pt + rule-c),
      text(size: 6.6pt, weight: "bold")[Weighted], [], [], [], text(size: 6.6pt, weight: "bold", asc.weighted), text(size: 6.6pt, weight: "bold", signed(asc.weighted_upside)), [])
    #small-note(asc.note)
    #if asc.at("bridge", default: ()).len() > 0 {
      v(3pt)
      text(size: 6.4pt, weight: "bold", fill: navy)[From the model DCF to our fair value]
      h(4pt)
      text(size: 6pt, fill: muted)[each step changes one input; the steps add up]
      v(-2pt)
      box(width: 62%, kv(asc.bridge, size: 6.5pt, bold-last: true))
    }
  ]
}
#let va = r.valuation
#if va == none or va.kind == none {
  section("Intrinsic value")[
    #text(fill: muted)[No intrinsic-value model is shown for this company.] #if va != none { small-note(va.notes.join(" ")) }
  ]
}
#if va != none and va.kind != none {
  col2(ratio: (1fr, 1.15fr), [
    #section("Discount rate")[ #kv(va.wacc, size: 6.6pt, bold-last: va.kind == "DCF") ]
  ], [
    #if va.kind == "DCF" [
      #section("From cash flows to value per share")[ #kv(va.bridge, size: 6.6pt, bold-last: true) ]
    ] else [
      #section("Dividend discount model")[ #kv(va.ddm, size: 6.6pt, bold-last: true) ]
    ]
  ])
  if va.kind == "DCF" {
    section(if asc != none { "Model DCF (cross-check)" } else { "DCF forecast" }, note: (if asc != none { "consensus revenue, then a fade · not in the rating, which uses the scenarios above · " } else { "" }) + "FCF margin " + va.assumptions.at(0).at(1) + " (3-year median) · terminal growth " + va.assumptions.at(1).at(1))[
      #year-table(va.forecast.years, va.forecast.rows, label: "Forecast year")
    ]
  }
  if "reverse" in va {
    section("What the price implies · reverse " + va.kind)[
      #col2(ratio: (1fr, 1.2fr), [
        #block(fill: navy-tint, inset: 7pt, radius: 2pt, width: 100%)[
          #text(size: 9pt, weight: "bold", fill: navy, va.reverse.headline)
        ]
      ], [
        #kv(va.reverse.rows, size: 6.6pt)
        #small-note(va.reverse.note)
      ])
    ]
  }
  let grid-table(g) = {
    let nc = g.cols.len()
    table(columns: (auto,) + (1fr,) * nc, stroke: none, inset: (x: 2.5pt, y: 2pt), align: (left,) + (center,) * nc,
      table.header(text(size: 5.8pt, fill: muted)[#g.row_label ↓ / #g.col_label →], ..g.cols.map(c => text(size: 6.2pt, weight: "bold", fill: muted, c))),
      table.hline(stroke: 0.4pt + rule-c),
      ..g.rows.map(rw => (text(size: 6.4pt, weight: "bold", fill: muted, rw.label),) + rw.cells.map(c => table.cell(
        fill: if c.base { navy-tint } else { none },
        text(size: 6.6pt, weight: if c.base { "bold" } else { "regular" },
          fill: if c.tone == "up" { pos-c } else if c.tone == "down" { neg-c } else { muted }, c.text)))).flatten())
  }
  if "grid1" in va and va.grid1 != none {
    section("Sensitivity · value per share (" + va.currency + ")", note: "green = above today's price, red = below; base case shaded")[
      #if "grid2" in va and va.grid2 != none {
        col2(grid-table(va.grid1), grid-table(va.grid2))
      } else { grid-table(va.grid1) }
    ]
  }
  if "mc" in va {
    section("Monte Carlo · distribution of " + va.mc.model + " value per share (" + va.currency + ")")[
      #col2(ratio: (1.4fr, 1fr), [
        #fit(w => histogram(va.mc, w, 30mm))
      ], [
        #kv(va.mc.rows, size: 6.5pt)
        #small-note[Inputs varied at random: #va.mc.assumptions. Seed #va.mc.seed (reproducible). A spread of model outcomes, not a forecast of the share price.]
      ])
    ]
  }
}

#if va != none and "band" in va {
  section("Own valuation history · P/E band", note: "5 years, trailing annual EPS")[
    #col2(ratio: (1.6fr, 1fr), [
      #fit(w => time-chart(((name: "P/E", color: "#2a78d6", points: va.band.points, w: 1.0),), va.band.yticks, va.band.xlabels,
        w, 30mm, refs: ((va.band.median_y, "5Y median", "#5B6475"),), band: (va.band.sd_lo, va.band.sd_hi)))
    ], [
      #kv(va.band.rows, size: 6.6pt)
      #small-note[Today's P/E is #va.band.reading its 5-year median. Shaded band = median ± 1 standard deviation. #va.band.note]
      #if va.band.at("rerating", default: "") != "" [#text(size: 6.3pt)[*Last 90 days.* #va.band.rerating]]
    ])
  ]
}

#if va != none and "consensus" in va {
  let c = va.consensus
  section("Street consensus", note: "third-party analyst estimates via " + c.source + "; not an InvestSync view")[
    #grid(columns: (0.9fr, 1fr, 1.9fr), column-gutter: 12pt, [
      #chart-title("Price targets (" + va.currency + ")")
      #kv(c.targets, size: 6.5pt)
    ], [
      #chart-title("Ratings distribution")
      #if c.dist.len() > 0 { fit(w => hbars(c.dist.map(d => (label: d.label, frac: d.frac, text: str(d.n))), w, label-w: 46pt, value-w: 14pt, size: 6pt)) } else { na("Ratings") }
    ], [
      #chart-title("Estimates (EPS in " + c.estimate_ccy + ")")
      #if c.estimates.len() > 0 {
        table(columns: (auto, 1fr, 1.6fr, 1fr, 1fr, 1fr, auto), stroke: none, inset: (x: 2pt, y: 1.5pt), align: (left,) + (right,) * 6,
          table.header(..([Period], [EPS], [Range], [EPS gr.], [Revenue], [Rev. gr.], [N]).map(x => text(size: 5.8pt, fill: muted, weight: "bold", x))),
          table.hline(stroke: 0.4pt + rule-c),
          ..c.estimates.map(e => e.map(x => text(size: 6.3pt, signed(x)))).flatten())
        small-note[Estimates may use an adjusted (non-GAAP / non-IFRS) EPS basis.]
      } else { na("Estimates") }
    ])
  ]
}

#if va != none and va.kind != none and va.notes.len() > 0 { small-note(va.notes.join(" ")) }
#v(2pt)
#ai-box(ai.valuation_overview, status: ai.status)

// =====================================================================================
// 7 · Broker research (street view)
// =====================================================================================
#if r.street != none {
  let sw = r.street
  v(12pt)  // flows on after Valuation (a forced break can strand a near-empty page)
  chapter(r.num.street, "Broker research", sub: if data-only { "what brokers say, compared with each other" } else { "what brokers say, compared with each other and with the InvestSync model" })
  block(below: 4pt, text(size: 6.4pt, fill: muted)[Third-party research from #link(sw.source_url)[#sw.source]#if sw.writeups_from != "" [; write-ups of individual notes from #sw.writeups_from]. Every broker is named and linked; ratings are mapped onto one five-step scale so they can be counted. These are the brokers' opinions, not InvestSync's.])
  col2(
    section("Comparison", note: "computed in code")[
      #for f in sw.findings [- #f]
    ],
    [
      #section("Latest rating per broker", note: if sw.agreement != "" { "agreement: " + sw.agreement + " (" + sw.agreement_reason + ")" } else { none })[
        #fit(w => hbars(sw.mix, w, label-w: 62pt, value-w: 18pt))
      ]
      #if sw.strip != none {
        let sp = sw.strip
        section("Price targets", note: sp.currency + " · one dot per broker (latest)")[
          #fit(w => {
            let ht = 20pt
            box(width: w, height: ht + 30pt, {
              for t in sp.ticks {
                place(top + left, dx: t.at(0) * w, dy: 0pt, line(start: (0pt, 0pt), end: (0pt, ht), stroke: 0.3pt + grid-c))
                place(top + left, dx: t.at(0) * w - 8pt, dy: ht + 2pt, text(size: 5.6pt, fill: muted, t.at(1)))
              }
              for d in sp.dots {
                place(top + left, dx: d * w - 2.6pt, dy: ht / 2 - 2.6pt, circle(radius: 2.6pt, fill: s1.transparentize(35%), stroke: none))
              }
              for (i, rf) in sp.refs.enumerate() {
                let col = rgb(rf.at(2))
                place(top + left, dx: rf.at(0) * w, dy: -2pt, line(start: (0pt, 0pt), end: (0pt, ht + 4pt), stroke: (paint: col, thickness: 1pt, dash: if i == 2 { "dashed" } else { none })))
                place(top + left, dx: calc.min(rf.at(0) * w, w - 60pt), dy: ht + 10pt + i * 6.5pt, text(size: 5.6pt, fill: col, weight: "bold", rf.at(1)))
              }
            })
          })
        ]
      }
    ],
    ratio: (1.15fr, 1fr))
  if sw.eps_rows.len() > 0 {
    section("EPS forecasts: how far apart the brokers are", note: sw.eps_currency + " per share · latest forecast per broker")[
      #table(columns: (auto, auto, 1.3fr, 1fr, 0.8fr, 1.2fr, 1.2fr), stroke: none, inset: (x: 3pt, y: 1.8pt),
        align: (left, right, right, right, right, right, right),
        table.header(..("Year", "Brokers", "Low – high", "Median", "Spread", "Median vs last actual", "Median vs Yahoo consensus").map(h => text(size: 6pt, fill: muted, weight: "bold", h))),
        table.hline(stroke: 0.4pt + rule-c),
        ..sw.eps_rows.map(r => r.map(x => text(size: 6.6pt, x))).flatten())
      #if sw.revision != "" { small-note[*Estimate trend* (median forecast, recent notes vs earlier notes): #sw.revision] }
    ]
  }
  section("Broker notes", note: "newest first · " + sw.currency + " targets · EPS in " + sw.eps_currency, breakable: true)[
    #table(columns: (auto, 1.3fr, 1.25fr, auto, auto) + (auto,) * sw.periods.len() + (auto,), stroke: none, inset: (x: 2.5pt, y: 1.6pt),
      align: (left, left, left, left, right) + (right,) * sw.periods.len() + (left,),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..(("Date", "Broker", "Rating (as published)", "Action", "Target") + sw.periods.map(p => p + " EPS") + ("Link",)).map(h => text(size: 6pt, fill: muted, weight: "bold", h))),
      ..sw.notes.map(n => (text(size: 6.3pt, n.date), text(size: 6.3pt, weight: "bold", n.broker), text(size: 6.3pt, n.rating),
        text(size: 6pt, fill: if n.action.starts-with("▲") { pos-c } else if n.action.starts-with("▼") { neg-c } else { muted }, n.action),
        text(size: 6.3pt, n.target)) + n.eps.map(x => text(size: 6.3pt, x)) + (if n.url != "" { link(n.url, text(size: 6pt, fill: s1, n.link)) } else { [] },)).flatten())
  ]
  if sw.summaries.len() > 0 {
    section(sw.summaries_title, note: sw.summaries_note, breakable: true)[
      #for m in sw.summaries {
        block(below: 4.5pt, breakable: false)[
          #text(size: 6.6pt)[*#m.broker*#if m.local != "" and m.local != m.broker [ (#m.local)] · #m.date#if m.rating != "" [ · #m.rating]#if m.target != "" [ · #m.target]#if m.via != "" [ · write-up: #m.via]#if m.url != "" [ · #link(m.url, text(fill: s1, m.link))]] \
          #if m.title != "" { text(size: 6.4pt, fill: muted)[#m.title] + linebreak() }
          #if m.summary_en != "" { text(size: 6.8pt)[#m.summary_en #text(size: 5.6pt, fill: ai-c)[(AI-condensed, figures checked against #if m.via != "" [the write-up] else [the broker's summary])]] } else if m.excerpt != "" { text(size: 6.3pt)[#m.excerpt #text(size: 5.6pt, fill: muted)[(#if m.via != "" [#m.via write-up] else [broker's own summary], excerpt#if data-only [ as published] else [; English summary needs the AI step])]] }
        ]
      }
    ]
  }
  v(2pt)
  ai-box(sw.synthesis, status: ai.status)
  small-note[#(sw.credit)Broker material is the copyright of each broker, and news write-ups of the publisher; the report shows short excerpts with credit and links for study purposes. Price targets older than 90 days may no longer reflect the broker's view. A-share brokers rarely publish price targets.]
  src("street")
}

// =====================================================================================
// 6 · Competitive landscape
// =====================================================================================
#if r.competitive != none { pagebreak(weak: true) } else { v(6pt) }
#chapter(r.num.competitive, "Competitive landscape")
#src("competitive")
#let cp = r.competitive
#if vm.comps != none {
  let c = vm.comps
  section("Relative valuation", note: "multiples vs peer median")[
    #table(
      columns: (1.75fr, 0.85fr, 0.95fr, 0.8fr, 0.8fr, 1fr, 0.75fr, 0.85fr), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
      align: (left, left, right, right, right, right, right, right),
      table.header(..("Company", "Ticker", "Mkt cap (" + c.currency + ")", "P/E TTM", "P/E fwd", "EV/EBITDA", "P/B", "Div yld TTM").map(x => text(fill: muted, size: 6.2pt, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..c.target.cells.map(x => table.cell(fill: navy-tint, strong(x))),
      ..c.peers.map(rw => rw.cells).flatten(),
      table.hline(stroke: 0.4pt + rule-c),
      ..c.median.cells.map(x => strong(x)),
      ..c.premium.enumerate().map(((i, x)) => if i == 0 { text(size: 6.2pt, fill: muted, x) } else { text(size: 6.6pt, signed(x)) }),
    )
  ]
}
#if cp != none {
  section("Operating comparison", note: "trailing twelve months, Yahoo Finance")[
    #table(
      columns: (1.75fr, 0.85fr, 1.05fr, 0.85fr, 0.8fr, 0.8fr, 0.8fr, 0.8fr), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
      align: (left, left, right, right, right, right, right, right),
      table.header(..("Company", "Ticker", "Revenue", "Rev. growth*", "Gross m.", "Op. m.", "Net m.", "ROE").map(x => text(fill: muted, size: 6.2pt, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..cp.rows.enumerate().map(((i, rw)) => rw.cells.map(x => if rw.bold { table.cell(fill: if i == 0 { navy-tint } else { none }, strong(signed(x))) } else { signed(x) })).flatten(),
    )
    #small-note[\*Revenue growth = latest quarter vs the same quarter a year earlier. Operating margin, gross margin, net margin and ROE: trailing twelve months (Yahoo Finance). #cp.method]
  ]
  if cp.scatter != none {
    col2(ratio: (1.2fr, 1fr), [
      #section("Price vs quality")[
        #chart-title("P/E (TTM) against return on equity")
        #fit(w => scatter(cp.scatter, w, 64mm, xlabel: "Return on equity →"))
        #small-note[Blue = this company, grey = peers; dashed lines = peer medians. Upper-left: expensive for its returns; lower-right: cheap for its returns.]
      ]
    ], [
      #v(9pt)
      #ai-box(ai.competitive_analysis, status: ai.status)
    ])
  } else { ai-box(ai.competitive_analysis, status: ai.status) }
} else { na("Peer data") }

// =====================================================================================
// 7 · Price & technical
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.technical, "Share price & technical indicators")
#src("technical")
#let tc = r.technical
#if tc != none {
  if tc.chart != none {
    section("Price, 50-day and 200-day moving averages", note: "2 years, adjusted closes · as of " + tc.as_of)[
      #legend(tc.chart.series.map(s => (s.name, s.color)))
      #fit(w => time-chart(tc.chart.series, tc.chart.yticks, tc.chart.xlabels, w, 46mm))
      #if tc.chart.volume.len() > 0 [
        #text(size: 5.6pt, fill: muted)[Volume (relative)]
        #fit(w => strip-bars(tc.chart.volume, w, 9mm))
      ]
      #if tc.chart.rsi.len() > 0 [
        #v(2pt)
        #text(size: 5.6pt, fill: muted)[RSI (14) · 70 overbought / 30 oversold]
        #fit(w => time-chart(((name: "RSI", color: "#2a78d6", points: tc.chart.rsi, w: 0.8),), ((0, "0"), (0.3, "30"), (0.7, "70"), (1, "100")), (), w, 13mm))
      ]
    ]
  }
  grid(columns: (1fr, 1fr), column-gutter: 14pt, [
    #section("Indicators")[ #kv(tc.indicators, size: 6.6pt) ]
    #section("Risk")[ #kv(tc.risk, size: 6.6pt) ]
  ], [
    #section("Rule-based signals")[
      #table(columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.8pt),
        ..tc.signals.map(sg => (text(size: 6.6pt, sg.at(0)), if sg.at(2) == "bullish" { chip("▲ " + sg.at(1), fill: pos-c) } else if sg.at(2) == "bearish" { chip("▼ " + sg.at(1), fill: neg-c) } else { chip("● " + sg.at(1), fill: rest, fg: ink) })).flatten(),
        table.hline(stroke: 0.4pt + rule-c),
        strong[Overall (majority of rules)], if tc.overall_key == "bullish" { chip("▲ " + tc.overall, fill: pos-c) } else if tc.overall_key == "bearish" { chip("▼ " + tc.overall, fill: neg-c) } else { chip("● " + tc.overall, fill: rest, fg: ink) })
      #small-note[Descriptive price indicators, not trading signals or a recommendation.]
    ]
    #section("Returns vs " + tc.bench)[
      #table(columns: (auto, 1fr, 1fr, 1fr), stroke: none, inset: (x: 2pt, y: 1.6pt), align: (left, right, right, right),
        table.header(..([], [#co.ticker], [#tc.bench], [Relative]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.4pt + rule-c),
        ..tc.returns.map(rw => (strong(rw.at(0)), signed(rw.at(1)), signed(rw.at(2)), signed(rw.at(3)))).flatten())
    ]
  ])
} else { na("Price history") }

// =====================================================================================
// 8 · News, catalysts & events
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.news, "Catalysts, news & events")
#src("news")
#let nw = r.news
#col2(ratio: (1fr, 1fr), [
  #section("Catalysts")[
    #if nw.catalysts.len() > 0 {
      for (i, b) in nw.catalysts.enumerate() { block(below: 4pt)[#chip(str(i + 1), fill: navy) *#b.title.* #b.text] }
    } else { ai-box(ai.at("catalysts", default: (title: "Investment catalysts", desc: "Three forward-looking catalysts from the latest report and news.", value: none)), status: ai.status) }
  ]
], [
  #section("Key risks")[
    #if nw.risks.len() > 0 {
      for b in nw.risks { block(below: 4pt)[#chip("!", fill: neg-c) *#b.title.* #b.text] }
    } else { ai-box(ai.at("risks", default: (title: "Downside risks", desc: "The two most important downside risks.", value: none)), status: ai.status) }
  ]
])
#col2(ratio: (1fr, 1fr), [
  #section("Upcoming and recent events")[
    #if nw.events.len() > 0 {
      table(columns: (auto, 1fr), stroke: none, inset: (x: 2pt, y: 1.8pt),
        ..nw.events.map(e => (text(size: 6.6pt, weight: "bold", e.at(0)), text(size: 6.6pt, e.at(1)))).flatten())
    } else { na("Event dates") }
  ]
], [
  #v(9pt)
  #ai-box(ai.events_to_monitor, status: ai.status)
])
#section("Company announcements", note: "official filings and exchange announcements, last 90 days")[
  #if nw.announcements.rows.len() > 0 {
    table(columns: (auto, 1.25fr, 2.4fr, auto), stroke: none, inset: (x: 2pt, y: 1.7pt),
      align: (left + horizon, left + horizon, left + horizon, right + horizon),
      fill: (_, row) => if calc.odd(row) { navy-tint } else { none },
      ..nw.announcements.rows.map(a => (
        text(size: 6.3pt, fill: muted, a.date),
        text(size: 6.3pt, weight: if a.important { "bold" } else { "regular" }, a.kind),
        text(size: 6.4pt, link(a.url, a.title)),
        text(size: 6pt, fill: muted, a.source))).flatten())
    small-note(nw.announcements.note)
  } else { na("Official announcements") }
]
#let news-tagged = nw.news.any(n => n.category != "")
#section("Recent news", note: if news-tagged { "sorted and translated by AI; figures checked against each item" } else { "headlines as published (Chinese sources in the original)" })[
  #if nw.news.len() > 0 {
    let tag(n) = if n.category == "" { [] } else {
      let col = if n.sentiment == "positive" { pos-c } else if n.sentiment == "negative" { neg-c } else { rest }
      let mark = if n.sentiment == "positive" { "▲" } else if n.sentiment == "negative" { "▼" } else { "●" }
      chip(mark + " " + n.category, fill: col, fg: if n.sentiment == "neutral" { ink } else { white })
    }
    table(columns: if news-tagged { (auto, auto, 1fr, auto) } else { (auto, 1fr, auto) }, stroke: none,
      inset: (x: 2pt, y: 1.7pt), align: (left + horizon, left + horizon, left + horizon, right + horizon),
      fill: (_, row) => if calc.odd(row) { navy-tint } else { none },
      ..nw.news.map(n => {
        let title = if n.url != "" { link(n.url, n.title) } else { n.title }
        let head = if n.original != "" [#text(size: 6.5pt, title) \ #text(size: 5.6pt, fill: muted, n.original)] else { text(size: 6.5pt, fill: if n.relevant { ink } else { muted }, title) }
        (text(size: 6.3pt, fill: muted, n.date),) + if news-tagged { (tag(n),) } else { () } + (head, text(size: 6pt, fill: muted, n.source))
      }).flatten())
  } else { na("News") }
]
#small-note[#nw.news_note Headlines link to the original article; the publisher is named on the right.]
#ai-box(ai.news_summary, status: ai.status)
#if nw.dividends != none {
  section("Dividend history")[
    #col2(ratio: (1.5fr, 1fr), [
      #if nw.dividends.chart != none { chart-title(nw.dividends.chart.title); fit(w => bar-chart(nw.dividends.chart, w, 26mm)) }
    ], [
      #table(columns: (1fr, auto), stroke: none, inset: (x: 0pt, y: 1.5pt),
        table.header(text(size: 6pt, fill: muted, weight: "bold")[Payment year], text(size: 6pt, fill: muted, weight: "bold")[DPS (#nw.dividends.currency)]),
        ..nw.dividends.rows.map(rw => (rw.at(0), align(right, rw.at(1)))).flatten())
      #small-note[Cash dividends by ex-dividend date, split-adjusted (Yahoo Finance).]
    ])
  ]
}


// =====================================================================================
// 9 · Ownership & governance
// =====================================================================================
#pagebreak(weak: true)
#chapter(r.num.ownership, "Ownership & governance")
#src("ownership")
#let ow = r.ownership
// round 8: 13F holder lists, insider trades and ISS scores read as "generic machine output"; they stay in the JSON
#if "split" in ow and ow.split.len() > 0 {
  section("Who owns the shares")[
    #box(width: 60%, fit(w => hbars(ow.split.map(s => (label: s.label, frac: s.frac, text: s.text)), w, label-w: 62pt, value-w: 32pt)))
    #small-note[Yahoo Finance estimate; categories can overlap for some listings.]
    #if ow.at("short", default: "") != "" [#text(size: 6.4pt)[#ow.short]]
  ]
}
#section("Management")[
  #if ow.officers.len() > 0 {
    table(columns: if ow.pay { (1.4fr, 2.4fr, auto) } else { (1.4fr, 2.8fr) }, stroke: none, inset: (x: 2.5pt, y: 1.7pt),
      align: (left, left, right),
      table.header(..(([Name], [Title]) + if ow.pay { ([Total pay],) } else { () }).map(x => text(size: 6.1pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..ow.officers.map(o => (o.at(0), o.at(1)) + if ow.pay { (o.at(3),) } else { () }).flatten())
    small-note[Source: Yahoo Finance. #if ow.pay [Pay from the latest proxy statement.] else [Pay not shown: the source does not state its currency for this listing.]]
  } else { na("Management data") }
]

// =====================================================================================
// 10 · Latest report
// =====================================================================================
#v(6pt)
#chapter(r.num.filings, if r.research.rows.len() > 0 { "Guidance, recent developments & the latest report" } else { "From the latest company report" })
#if not data-only { ai-box(ai.report_summary, status: ai.status) }  // data-only: the reader's box follows the excerpts
#if r.research.rows.len() > 0 {
  section("Research notes", note: "dated facts read from results releases, announcements, broker reports and news", breakable: true)[
    #table(columns: (auto, auto, auto, 1fr, 0.42fr), stroke: none, inset: (x: 2.5pt, y: 1.8pt),
      align: (left, left, left, left, left),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..([\#], [Date], [Topic], [Fact], [Source]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..r.research.rows.map(x => (text(size: 6pt, fill: muted, x.at(0)), text(size: 6.1pt, x.at(1)), text(size: 6.1pt, weight: "bold", x.at(2)),
        text(size: 6.3pt, x.at(3)), if x.at(5) != "" { link(x.at(5))[#text(size: 5.8pt, fill: navy, x.at(4))] } else { text(size: 5.8pt, x.at(4)) })).flatten())
    #if r.research.gaps.len() > 0 { small-note[Not found in the documents read: #r.research.gaps.join("; ").] }
    #small-note[#r.research.note]
  ]
}
// round 8: raw filing text (10-K risk-factor boilerplate) next to the research notes was padding; shown only when
// the research step did not run
#if r.filings.len() > 0 and r.research.rows.len() == 0 {
  for f in r.filings {
    section(f.title, note: f.source + if f.filed != "" { " · filed " + f.filed } else { "" }, breakable: true)[
      #for s in f.sections {
        block(below: 5pt, breakable: true)[
          #text(size: 6.8pt, weight: "bold", fill: navy, s.at(0)) \
          #text(size: 6.4pt, fill: ink, s.at(1))
        ]
      }
      #if f.skipped.len() > 0 { small-note[Not shown (the text found looked like a contents page, not prose): #f.skipped.join(", ").] }
      #small-note[Excerpt in the original language. Full document: #link(f.url)[#f.url] #if cites.refs.at("filings", default: "") != "" [· #cites.refs.at("filings")]]
    ]
  }
} else if r.research.rows.len() == 0 {
  section("Report excerpts")[#text(fill: muted, size: 6.6pt)[The latest annual / interim report was not read for this run (still downloading, or disabled with --no-filings).]]
}
#if data-only { ai-box(ai.report_summary, status: ai.status) }

// (Appendix · evidence index removed 9 Nov 2026, round 8: S/E codes are not printed in the text; arguments show their
// evidence inline, and research-note ids resolve in the notes table above.)

// =====================================================================================
// Appendix · Scorecard (moved to the back 9 Nov 2026: blind reviewers called the yes/no checks templated on page 2)
// =====================================================================================
#if r.scorecard != none {
  pagebreak(weak: true)
  chapter(r.num.scorecard, "Appendix: quality scorecard", sub: "yes/no checks in five areas · descriptive only, never feeds the rating")
  let sc = r.scorecard
  let mark(stt) = if stt == "pass" { text(fill: st-good, weight: "bold", "✓") } else if stt == "fail" { text(fill: st-crit, weight: "bold", "×") } else { text(fill: muted, "–") }
  let area-box(a) = block(width: 100%, breakable: false, below: 8pt)[
    #grid(columns: (1fr, auto), align: (left + bottom, right + bottom),
      text(size: 8pt, weight: "bold", fill: navy, a.title),
      [#box(width: 40pt, height: 4pt, fill: grid-c, radius: 1.5pt, place(left, box(width: 40pt * a.frac, height: 4pt, radius: 1.5pt, fill: if a.frac >= 0.67 { st-good } else if a.frac >= 0.34 { st-warn } else { st-crit }))) #h(3pt) #text(size: 8pt, weight: "bold")[#a.score / #a.available]])
    #v(-3pt)
    #line(length: 100%, stroke: 0.5pt + navy)
    #v(-1pt)
    #if a.checks.len() == 0 { text(size: 6.4pt, fill: muted, a.note) } else {
      table(columns: (10pt, 1.05fr, 1.5fr), stroke: none, inset: (x: 2pt, y: 1.6pt), align: (center + horizon, left + horizon, left + horizon),
        fill: (_, row) => if calc.odd(row) { navy-tint } else { none },
        ..a.checks.map(c => (mark(c.status), text(size: 6.5pt, weight: "bold", c.name), text(size: 6.3pt, fill: if c.status == "na" { muted } else { ink }, c.detail))).flatten())
      if a.note != "" { small-note(a.note) }
    }
  ]
  grid(columns: (1fr, 1fr), column-gutter: 12pt,
    [#for a in sc.areas.slice(0, 3) { area-box(a) }],
    [#for a in sc.areas.slice(3) { area-box(a) }
     #if sc.piotroski != none { area-box(sc.piotroski) }])
  small-note[Checks follow the yes/no tests in Simply Wall St's published analysis model (github.com/SimplyWallSt/Company-Analysis-Model, CC BY-NC-SA 4.0), adapted by InvestSync: the company's peers stand in for "the market", dividend-yield cut-offs are fixed per market (CN 1.5% / 3.5%, HK 3% / 6%, US 1.5% / 4%), and future growth uses the brokers' median EPS forecasts where available, else the Yahoo Finance consensus. "–" = not enough data. Piotroski F-score: Piotroski (2000), nine tests comparing the latest fiscal year with the one before.]
}

// =====================================================================================
// 11 · Methodology & disclosures
// =====================================================================================
#v(6pt)
#chapter(r.num.methodology, "Methodology, sources & disclosures")
#section("How the numbers are made")[
  #set text(size: 6.7pt)
  #for m in r.methodology [- #m]
]
#section("Sources & citations", note: "every data source used in this report, with how and when it was retrieved (UTC)", breakable: true)[
  #if cites.rows.len() > 0 {
    table(columns: (auto, 1.5fr, 1.35fr, 1.25fr, auto, 1.5fr), stroke: none, inset: (x: 2.5pt, y: 1.9pt),
      align: (right, left, left, left, left, left),
      fill: (_, row) => if row > 0 and calc.even(row) { navy-tint } else { none },
      table.header(..([\#], [Data], [Original source], [Accessed via], [Retrieved], [Link]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
      table.hline(stroke: 0.5pt + navy),
      ..cites.rows.map(c => (
        text(size: 6.2pt, weight: "bold", "[" + str(c.n) + "]"), text(size: 6.2pt, c.what), text(size: 6.2pt, c.publisher),
        text(size: 5.9pt, fill: muted, c.via), text(size: 5.9pt, c.retrieved),
        text(size: 5.9pt, link(c.url, c.url_short)))).flatten())
    small-note[Cached data show the time it was originally fetched (statements are re-fetched after 30 days, prices after 15 minutes). Data accessed through AKShare and yfinance are third-party compilations of the original publishers' data; check the original filing before relying on a figure. News publishers are named next to each headline in chapter 8.]
  } else {
    text(size: 6.7pt, vm.footer.sources)
  }
]
#if vm.footer.warnings.len() > 0 {
  section("Data notes for this company")[ #set text(size: 6.7pt); #for w in vm.footer.warnings [- #w] ]
}
#if r.at("disclosures", default: none) != none {
  let dz = r.disclosures
  section("Disclosures", note: if data-only { "who produced this note" } else { "who produced this note, and the rating history for this stock" })[
    #text(size: 6.7pt)[#dz.producer]
    #if dz.history.len() > 0 {
      v(2pt)
      table(columns: (auto, auto, auto, auto, 1fr), stroke: none, inset: (x: 2.5pt, y: 1.5pt),
        table.header(..([Report (price date)], [Rating], [Fair value], [Price], [Basis]).map(x => text(size: 6pt, fill: muted, weight: "bold", x))),
        table.hline(stroke: 0.4pt + rule-c),
        ..dz.history.map(h => h.map(x => text(size: 6.2pt, x))).flatten())
      small-note[Earlier reports from saved runs of this tool; a change of basis (method) makes ratings and fair values not comparable.]
    }
    #if dz.at("distribution", default: "") != "" [#text(size: 6.4pt)[#dz.distribution]]
  ]
}
#section("Disclaimer")[
  #text(size: 6.7pt)[#vm.footer.disclaimer]
  #small-note[Generated #vm.footer.generated by InvestSync Research Tools.#if ai.model != "" [ AI commentary by #ai.model; the figures it quotes are matched to the data in code, which does not prove every statement right.]]
]
