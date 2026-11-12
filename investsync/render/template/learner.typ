// InvestSync Research Tools: learner's guide.
// Page 1 introduces the guide; page 2 is the tear sheet with orange step markers (1-8); the guide that follows walks a first-year
// student through it with this company's own numbers. Data: viewmodel.py + learner_vm.py.

#import "lib.typ": *
#import "learner_visuals.typ": *

#let vm = json(sys.inputs.at("data"))
#let g = vm.learner
#let co = vm.company
#let orange = rgb("#E8590C")
#let orange-tint = rgb("#FDF0E8")

#set document(title: co.name + " (" + co.ticker + ") · InvestSync Learner's Guide", author: "InvestSync Research Tools")

#set text(font: ("Inter", "Helvetica Neue", "Helvetica", "Arial", "PingFang SC", "Hiragino Sans GB", "STHeiti", "Noto Sans CJK SC", "Noto Sans SC"),
          size: 10pt, fill: ink, lang: "en")
#set par(leading: 0.55em, spacing: 0.8em, justify: false)
#set page(
  paper: "a4",
  margin: (x: 14mm, top: 15mm, bottom: 13mm),
  header: context [
    #grid(columns: (auto, 1fr), align: (left + horizon, right + horizon),
      image("../assets/investsync-logo.png", height: 5.2mm),
      text(size: 6.4pt, fill: muted)[*#co.name* · #co.ticker · Learner's guide · #vm.date])
    #v(-3pt)
    #line(length: 100%, stroke: 0.6pt + orange)
  ],
  footer: context [
    #line(length: 100%, stroke: 0.4pt + rule-c)
    #v(-3pt)
    #grid(columns: (1fr, auto),
      text(size: 5.8pt, fill: muted)[InvestSync Research Tools · for education within the InvestSync Student Investment Organization (CUHK-Shenzhen) · the AI rating is a model output, not investment advice],
      text(size: 6pt, fill: muted, counter(page).display("1 / 1", both: true)))
  ],
)

#let num-badge(n, size: 16pt) = box(baseline: 25%, circle(radius: size / 2, fill: orange, stroke: none,
  align(center + horizon, text(size: size * 0.55, weight: "bold", fill: white, n))))
#let label-text(t) = text(size: 8.2pt, weight: "bold", fill: navy, tracking: 0.06em, upper(t))

// ---------------------------------------------------------------- intro
#block(below: 8pt)[
  #text(size: 20pt, weight: "bold", fill: navy)[Learner's guide] \
  #text(size: 10pt, fill: muted)[How to read the #co.name report, step by step]
]
#grid(columns: (1.25fr, 1fr), column-gutter: 12pt,
  block(width: 100%)[
    #label-text("Who this is for") \
    First-year students with no finance background. Every term is explained the first time it appears (the words box below and the glossary at the end). The guide walks through the report in the order an analyst reads it, using this company's own numbers.

    #label-text("How to use it") \
    Keep page 2 (the one-page tear sheet) open next to this guide. The orange numbers #num-badge("1", size: 9pt) to #num-badge("8", size: 9pt) on page 2 match the eight steps. Each step shows where to look, the numbers, how to read them, a worked calculation, red flags and a question to ask yourself. Try the exercises at the end before you look at the answers.
  ],
  block(width: 100%, fill: orange-tint, inset: 8pt, radius: 3pt)[
    #label-text("The 60-second version") #if g.ai [#h(3pt) #chip("AI-written", fill: ai-c)]
    #v(2pt)
    #par(justify: true, g.big_picture)
  ],
)
#v(4pt)
#text(size: 7.5pt, fill: muted, vm.footer.disclaimer)
#v(2pt)
#block(width: 100%, inset: (x: 8pt, y: 5pt), stroke: (left: 2pt + navy), fill: navy-tint)[
  #text(size: 9pt)[*The eight steps:* #for (i, s) in g.steps.enumerate() [#if i > 0 [ · ]#num-badge(s.n, size: 9pt) #s.title]]
]

#v(8pt)
#let first-words = ("Revenue", "Gross margin", "Net margin", "EPS", "ROE", "P/E", "Forward P/E", "EV/EBITDA",
  "Net debt", "Cash conversion", "Accruals ratio", "DCF", "Fair value", "AI rating", "Overall view", "Beta")
#let fw = g.glossary.filter(t => t.term in first-words)
#block(width: 100%, inset: 8pt, radius: 3pt, stroke: 0.5pt + rule-c)[
  #label-text("Words you will meet on the tear sheet (page 2)") #h(4pt) #text(size: 8pt, fill: muted)[the full glossary is at the end]
  #v(3pt)
  #if g.at("fy_note", default: "") != "" [#text(size: 9.1pt)[*Reading the dates:* #g.fy_note] #v(3pt)]
  #let h2 = calc.ceil(fw.len() / 2)
  #grid(columns: (1fr, 1fr), column-gutter: 12pt,
    [#set text(size: 9.1pt); #for t in fw.slice(0, h2) [*#t.term:* #t.meaning \ #v(1.5pt)]],
    [#set text(size: 9.1pt); #for t in fw.slice(h2) [*#t.term:* #t.meaning \ #v(1.5pt)]])
]

// the annotated tear sheet the steps refer to (page 2): the beginner reads the introduction first (reviewers,
// 8 Nov 2026: opening on a dense page of jargon put first-year readers off)
#pagebreak()
#include "tearsheet.typ"
#pagebreak(weak: true)

// ---------------------------------------------------------------- at a glance + life-cycle phase (built in code)
#let vis = g.visuals
#let step-of = (growth: "2", profit: "3", safety: "4", cheap: "5")

#block(below: 6pt)[
  #grid(columns: (1fr, auto), align: (left + bottom, right + bottom),
    text(size: 18pt, weight: "bold", fill: navy)[At a glance],
    box(fill: lv-orange-tint, stroke: 0.6pt + orange, inset: (x: 6pt, y: 3pt), radius: 3pt,
      text(size: 7.4pt, weight: "bold", fill: orange)[MODEL OUTPUT · NOT INVESTMENT ADVICE]))
  #text(size: 9.5pt, fill: muted)[#co.name on one page: where it is in its life cycle, four simple scales and what the model's valuation says. Everything here is computed from the report's data by fixed rules; the pages that follow explain each item.]
]
#let ph = vis.phase
#card-pair(style-a: (fill: navy), style-b: (stroke: 0.6pt + rule-c),
  [
    #text(size: 7.4pt, weight: "bold", fill: white.transparentize(30%), tracking: 0.08em)[LIFE-CYCLE PHASE · NEXT PAGE]
    #if ph != none [
      \ #text(size: 20pt, weight: "bold", fill: white)[#ph.n] #text(size: 10pt, fill: white.transparentize(25%))[of 5] #h(4pt) #text(size: 13pt, weight: "bold", fill: white, ph.name)
      #v(1pt)
      #grid(columns: (1fr,) * 5, column-gutter: 2pt, ..range(5).map(i => box(width: 100%, height: 5pt, radius: 2pt,
        fill: if i + 1 == ph.n { orange } else if ph.alt != none and i + 1 == ph.alt { white.transparentize(45%) } else { white.transparentize(80%) })))
      #v(2pt)
      #text(size: 8.6pt, fill: white, ph.short)#if ph.alt != none [ #text(size: 8.2pt, fill: white.transparentize(20%), style: "italic")[Borderline with phase #ph.alt (#ph.alt_name).]]
    ] else [ \ #text(size: 9pt, fill: white)[Not enough data to place the company in a phase.]]
  ],
  [
    #lv-label("AI rating, as the report states it")
    #let r = vis.glance.rating
    #if r != none [
      \ #v(2pt) #rating-badge(r.rating, size: 12pt) #h(6pt) #if r.fair_t != "" [#text(size: 9.5pt)[fair value *#r.fair_t* · #signed(r.upside_t) vs the price]]
      #v(3pt)
      #text(size: 8pt, fill: muted)[Set in code from #r.basis. Rule: #r.rule. A model output, not advice.]
    ] else [ \ #text(size: 9pt, fill: muted)[This report has no AI rating, so none is shown here.]]
  ],
)
#v(6pt)
#block(width: 100%, stroke: 0.6pt + rule-c, radius: 4pt, inset: (x: 9pt, y: 7pt))[
  #lv-label("Four scales") #h(4pt) #text(size: 7.6pt, fill: muted)[each compares the company with its peers or with its own past, not with a universal pass mark]
  #for c in vis.glance.scales {
    v(5pt)
    grid(columns: (128pt, 1fr), column-gutter: 8pt, align: (left + horizon, left + horizon),
      [#text(size: 9pt, weight: "bold", fill: navy, c.title) \ #text(size: 7pt, fill: muted)[#if c.basis != "" [#c.basis · ]step #step-of.at(c.key)]],
      scale-track(c.levels, c.chosen, size: 6.6pt, ht: 15pt))
    grid(columns: (128pt, 1fr), column-gutter: 8pt, [], text(size: 8pt, c.evidence))
  }
]
#if vis.glance.range != none {
  v(6pt)
  block(width: 100%, stroke: 0.6pt + rule-c, radius: 4pt, inset: (x: 9pt, y: 7pt))[
    #lv-label("Price against the model's value") #h(4pt) #text(size: 7.6pt, fill: muted)[#vis.glance.range.currency per share#if vis.glance.range.range != none [; shaded: from the bear to the bull scenario]]
    #v(2pt)
    #fit(wd => value-strip(vis.glance.range, wd))
    #text(size: 7.8pt, fill: muted)[The scenarios and the fair value are the model's estimates (step 6 shows how they are built). If the price sits inside the shaded range, the model's own scenarios disagree about whether it is cheap or dear.]
  ]
}
#v(6pt)
#block(width: 100%, fill: navy-tint, radius: 4pt, inset: 8pt)[
  #set text(size: 8.6pt)
  *How to use this page.* Read it as a map, not an answer: each scale is one sentence of evidence, and the next page explains the life-cycle phase. The AI rating comes from a fixed rule applied to the model's fair value; the scales do not change it. A strong business can be expensive and a cheap share can be a weak business, so look at all of them together.
]

#if ph != none {
  pagebreak()
  block(below: 6pt)[
    #text(size: 18pt, weight: "bold", fill: navy)[Where is #co.name in its life cycle?] \
    #text(size: 9.5pt, fill: muted)[Companies tend to pass through five phases, from start-up to decline. Three yes/no questions, answered from the numbers, place #co.name in one of them, and the phase tells you which valuation measure is useful.]
  ]
  card-pair(ratio: (1.5, 1), style-a: (stroke: 0.6pt + rule-c), style-b: (fill: navy),
    [
      #for (i, q) in ph.questions.enumerate() {
        if i > 0 { line(length: 100%, stroke: 0.4pt + rule-c) }
        grid(columns: (1fr, auto), column-gutter: 6pt, align: (left + horizon, right + horizon),
          block(above: 3pt, below: 3pt)[#text(size: 10pt, weight: "bold", fill: navy, q.q) \ #text(size: 8.2pt, fill: muted, q.fig)],
          yn-chip(q.a))
      }
    ],
    [
      #text(size: 7.4pt, weight: "bold", fill: white.transparentize(30%), tracking: 0.08em)[PHASE] \
      #text(size: 22pt, weight: "bold", fill: white)[#ph.n] #text(size: 10pt, fill: white.transparentize(25%))[of 5] \
      #text(size: 13pt, weight: "bold", fill: white, ph.name) \
      #v(1pt)
      #text(size: 8.6pt, fill: white, ph.short)
      #if ph.alt != none [ \ #text(size: 8.2pt, fill: white.transparentize(15%), style: "italic")[Borderline with phase #ph.alt (#ph.alt_name).]]
    ],
  )
  v(5pt)
  block(width: 100%, stroke: 0.6pt + rule-c, radius: 4pt, inset: (x: 9pt, y: 6pt))[
    #lv-label("Revenue and " + ph.profit_label) #h(4pt) #text(size: 7.4pt, fill: muted)[#ph.currency · fiscal years#if ph.trend.points.any(p => p.ttm) [ and the last twelve months (TTM)]] #h(1fr)
    #box(width: 7pt, height: 7pt, fill: navy.transparentize(55%), radius: 1pt) #text(size: 7pt)[Revenue] #h(5pt)
    #box(width: 7pt, height: 7pt, fill: pos-c, radius: 1pt) #text(size: 7pt)[#upper(ph.profit_label.first())#ph.profit_label.slice(1)]
    #fit(wd => trend-bars(ph.trend, wd, 62pt))
  ]
  v(5pt)
  block(width: 100%)[
    #lv-label("The five phases") #h(4pt) #text(size: 7.4pt, fill: muted)[a typical path; real companies can skip phases or move back]
    #v(2pt)
    #fit(wd => phase-diagram(ph, co.ticker + " is here", wd, 150pt))
  ]
  v(5pt)
  card-pair(pad: 8pt, style-a: (fill: orange-tint), style-b: (stroke: 0.6pt + rule-c),
    [
      #text(size: 7.6pt, weight: "bold", fill: orange, tracking: 0.06em)[WHICH MEASURE IS USEFUL HERE?] \
      #text(size: 9pt, ph.measure)
    ],
    [
      #lv-label("Why this phase") \
      #text(size: 9pt, ph.why)
      #for n in ph.notes [ \ #text(size: 8.2pt, fill: muted, n)]
    ],
  )
  v(5pt)
  block(width: 100%, inset: (left: 7pt, y: 2pt), stroke: (left: 1.6pt + navy))[
    #text(size: 7.6pt, weight: "bold", fill: navy, tracking: 0.06em)[HOW THE PHASE IS DECIDED (FIXED RULES IN CODE)] \
    #set text(size: 8pt)
    #for (i, r) in ph.rules.enumerate() [#(i + 1). #r \ ]
    #text(size: 7.6pt, fill: muted)[Growth uses revenue over up to five fiscal years and the latest period; profit is operating profit (net profit for banks and insurers), over the last twelve months when available; payouts are dividends plus buybacks over the last two fiscal years. The 10% and "half of profit" lines are conventions, not laws.]
  ]
}


// ---------------------------------------------------------------- steps
// pictures for a step: the segment bar and region map (step 1), a scale card (steps 2-5), the P/E history (step 5)
#let step-visuals(s) = {
  if s.key == "business" and (vis.segments != none or vis.map != none) {
    block(width: 100%, above: 8pt, breakable: false, {
      let seg = if vis.segments != none { block(width: 100%)[
        #lv-label("Revenue by segment") #h(3pt) #text(size: 7.4pt, fill: muted)[#vis.segments.period · total #vis.segments.currency #vis.segments.total_t]
        #v(2pt)
        #fit(wd => seg-bar(vis.segments, wd))
      ] }
      let geo = if vis.map != none { block(width: 100%)[
        #lv-label("Revenue by region") #h(3pt) #text(size: 7.4pt, fill: muted)[#vis.map.period · darker = larger share]
        #v(2pt)
        #fit(wd => geo-block(vis.map, wd))
        #text(size: 7pt, fill: muted)[Companies report regions in their own way, often by where the customer is billed rather than where the product ends up.#if vis.map.dots [ Small places (such as Hong Kong) are shown as dots with an orange ring.]]
      ] }
      if seg != none and geo != none { grid(columns: (1fr, 1.15fr), column-gutter: 12pt, seg, geo) }
      else if seg != none { seg } else { align(center, box(width: 70%, geo)) }
    })
  }
  if s.at("scale", default: none) != none { scale-card(s.scale) }
  if s.key == "cheap" and vis.pe != none {
    block(width: 100%, above: 7pt, breakable: false)[
      #lv-label("P/E over the last five years against its own history") #h(3pt) #text(size: 7.4pt, fill: muted)[#vis.pe.metric; bands = fifths of its own history]
      #v(1pt)
      #fit(wd => pe-chart(vis.pe, wd, 92pt))
      #text(size: 7.2pt, fill: muted)[Each shaded band holds a fifth of the past five years' P/E readings (cut-offs #vis.pe.cuts_t.join(" · ")); median #vis.pe.median_t.#if vis.pe.log [ The scale doubles at each line because the P/E swung a lot: a P/E shoots up when profit collapses, which says more about the profit than the price.]#if vis.pe.note != "" [ #vis.pe.note]]
    ]
  }
}
#let step-block(s) = block(width: 100%, breakable: true, above: 12pt)[
  #block(sticky: true, below: 4pt)[
    #grid(columns: (auto, 1fr), column-gutter: 7pt, align: (left + horizon, left + horizon),
      num-badge(s.n, size: 20pt),
      [#text(size: 12pt, weight: "bold", fill: navy, s.title) \ #text(size: 8.5pt, fill: muted)[Look at: #s.look]])
  ]
  #line(length: 100%, stroke: 0.6pt + orange)
  #v(1pt)
  #text(size: 9.5pt, style: "italic", s.why)
  #grid(columns: (1.1fr, 1fr), column-gutter: 12pt,
    [
      #label-text("This company's numbers")
      #if s.rows.len() > 0 {
        table(columns: (1.15fr, 1fr), stroke: none, inset: (x: 2pt, y: 2pt),
          fill: (_, row) => if calc.even(row) { navy-tint } else { none },
          ..s.rows.map(r => (text(size: 8.8pt, r.label), [#text(size: 9pt, weight: "bold", r.value)#if r.note != "" [ \ #text(size: 7.8pt, fill: muted, r.note)]])).flatten())
      } else { text(size: 8.8pt, fill: muted)[Not available for this company.] }
    ],
    [
      #label-text("How to read it")
      #set text(size: 9.2pt)
      #for h in s.how [- #h]
    ],
  )
  #step-visuals(s)
  #if s.worked != none {
    block(width: 100%, fill: rgb("#F6F7FA"), inset: 7pt, radius: 3pt, above: 6pt, breakable: false)[
      #label-text("Worked example") #h(3pt) #text(size: 8.8pt, weight: "bold", s.worked.title)
      #v(1pt)
      #for l in s.worked.lines [#text(font: ("Menlo", "DejaVu Sans Mono", "Courier New"), size: 8.8pt, l) \ ]
    ]
  }
  #if s.ai != "" {
    block(width: 100%, inset: (left: 7pt, y: 3pt), stroke: (left: 1.6pt + ai-c), above: 6pt)[
      #chip("How an analyst reads it · AI-written", fill: ai-c) \
      #text(size: 9.2pt, s.ai)
    ]
  }
  #grid(columns: (1fr, 1fr), column-gutter: 12pt, row-gutter: 0pt,
    block(above: 6pt)[
      #text(size: 8.2pt, weight: "bold", fill: neg-c, tracking: 0.06em, "RED FLAGS")
      #set text(size: 9pt)
      #for f in s.flags [- #f]
    ],
    block(above: 6pt, width: 100%, fill: orange-tint, inset: 6pt, radius: 3pt)[
      #text(size: 8.2pt, weight: "bold", fill: orange, tracking: 0.06em, "ASK YOURSELF") \
      #text(size: 9.5pt, weight: "bold", s.ask)
    ],
  )
]

// final run (10 Nov 2026): each step starts on its own page, with the text 25% larger, so the guide reads as a
// workbook (10-16 pages) rather than a dense 7-page leaflet
#pagebreak(weak: true)
#for (i, s) in g.steps.enumerate() { if i > 0 { pagebreak(weak: true) }; step-block(s) }

// ---------------------------------------------------------------- exercises, answers, checklist, glossary
#v(14pt)
#block(below: 6pt, text(size: 14pt, weight: "bold", fill: navy)[Try it yourself])
#text(size: 9.5pt)[Work these out with a calculator before you turn to the answers. Every number you need is on the tear sheet (page 2).]
#v(2pt)
#for (i, e) in g.exercises.enumerate() {
  block(width: 100%, above: 7pt, breakable: false)[
    #num-badge(str(i + 1), size: 12pt) #h(3pt) #text(size: 10pt, weight: "bold", e.q) \
    #h(17pt) #text(size: 8.5pt, fill: muted)[Where to look: #e.where]
  ]
}
#v(6pt)
#block(width: 100%, fill: navy-tint, inset: 8pt, radius: 3pt)[
  #label-text("Discussion questions for the club")
  #set text(size: 9.5pt)
  #for (i, d) in g.discussion.enumerate() [#(i + 1). #d \ ]
]
#v(6pt)
#block(width: 100%, inset: 8pt, radius: 3pt, stroke: 0.6pt + rule-c)[
  #label-text("Before you form a view: checklist")
  #set text(size: 9.2pt)
  #for c in g.checklist [#box(width: 7pt, height: 7pt, stroke: 0.6pt + muted, radius: 1pt) #h(3pt) #c \ ]
]
// 12 Nov 2026: the questions an analyst would ask about this company (question bank + recent evidence), as homework:
// no answers here, even when the deep report answered them
#let hw = g.at("questions", default: ())
#if hw.len() > 0 {
  v(6pt)
  block(width: 100%, inset: 8pt, radius: 3pt, stroke: 0.8pt + orange)[
    #label-text("Your homework: questions an analyst would ask")
    #v(1pt)
    #text(size: 9pt)[Analysts ask these about #co.name. There is no answer key: answer each in two or three sentences from this guide and the full report, then compare your answers at the club. A hint is a figure worked out from the data; "new" questions come from recent news about the company.]
    #for q in hw {
      block(above: 6pt, below: 0pt, breakable: false, grid(columns: (15pt, 1fr), column-gutter: 3pt,
        num-badge(q.n, size: 11pt),
        [
          #text(size: 9.5pt, weight: "bold", q.q) \
          #text(size: 8pt, fill: muted)[#q.theme#if q.new [ · new]#if q.where != "" [ · look at #q.where]]
          #if q.why != "" [ \ #text(size: 8.2pt)[_Why now:_ #q.why]]
          #if q.hint != "" [ \ #text(size: 8.2pt)[_Hint:_ #q.hint]]
        ]))
    }
  ]
}

#pagebreak(weak: true)
#block(below: 6pt, text(size: 14pt, weight: "bold", fill: navy)[Answers])
#for (i, e) in g.exercises.enumerate() {
  block(width: 100%, above: 7pt, breakable: false)[
    #num-badge(str(i + 1), size: 12pt) #h(3pt) #text(size: 10pt, weight: "bold")[#e.answer] \
    #for l in e.working [#h(17pt) #text(font: ("Menlo", "DejaVu Sans Mono", "Courier New"), size: 8.8pt, l) \ ]
  ]
}
#v(10pt)
#block(below: 4pt, text(size: 14pt, weight: "bold", fill: navy)[Glossary])
#let half = calc.ceil(g.glossary.len() / 2)
#grid(columns: (1fr, 1fr), column-gutter: 14pt,
  [#set text(size: 9pt); #for t in g.glossary.slice(0, half) [*#t.term:* #t.meaning \ ]],
  [#set text(size: 9pt); #for t in g.glossary.slice(half) [*#t.term:* #t.meaning \ ]])
#v(6pt)
#small-note[#if vm.footer.warnings.len() > 0 [*Data notes (tear sheet, page 2):* #vm.footer.warnings.join(" · ") \ ]*Generated* #vm.footer.generated by InvestSync Research Tools#if vm.narrative != none and vm.narrative.model != "" [; AI commentary by #vm.narrative.model, its figures matched to the data in code]. *Sources:* listed in the full research report. Not investment advice; full disclaimer: page 1.]
#small-note[The guide is built in code from the same data as the report, so every number and worked example matches the tear sheet (page 2) exactly. The "how an analyst reads it" notes and the 60-second version (when shown with the AI chip) are written by an AI model and checked like the report: every figure must appear in the data, and the AI may not state a rating other than the rule-based one. Rules of thumb are comparisons, not universal cut-offs: what is normal differs by industry.]
