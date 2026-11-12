"""Claim check: each risky claim in the AI prose is checked on its own against the writer's sources.

Why: in the 8 Nov 2026 final-checker experiment one Opus pass found 12 material prose errors in three DeepSeek
deep reports, while DeepSeek asked to "find the errors" in the whole report found 2-3. The literature explains the
gap: models are poor at finding errors in a long text of their own but good at answering narrow questions about one
claim at a time with the draft out of view (Chain-of-Verification, factored variant; Dhuliawala et al. 2023) and at
applying an explicit checklist (TICK; Cook et al. 2024). So:

1. Code picks the sentences that can be wrong in the ways reviewers found: direction and trend words, causes,
   explanations of the model or rating, comparisons, funding / balance-sheet claims (``candidates``).
2. DeepSeek checks a handful at a time against the sources (facts, research notes, news, filings) with the
   CHECKLIST below; the sources come first in every call, so the provider's prefix cache makes repeats cheap.
3. Code keeps a problem only if the claim is really in the draft and the evidence it cites is really in the
   sources (an invented objection is dropped, and true claims backed by the sources are not removed).
4. The writer then fixes the flagged sentences (same revision loop as the deep reviewer).
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

import dspy
from pydantic import BaseModel, Field

from .. import provenance
from ..schema import ReviewNote

log = logging.getLogger(__name__)

CHECKLIST = """Check each claim against the sources with these questions, in order:
1. Direction: do rise / fall, accelerating / slowing, improving / worsening, above / below, cheap / expensive,
   premium / discount match the figures? Judge the current trend from the latest reported period (year to date
   and latest quarter vs a year earlier), not from fiscal-year history. "Re-accelerated" needs growth faster
   than before; a slower rate is slowing even if still positive.
2. Cause: a reason for a change ("as", "because", "due to", "driven by", "reflecting", "amid", "thanks to")
   must be stated in the sources (facts, research notes, filings, news). A plausible cause that no source
   gives is unsupported. A cause the sources contradict is wrong.
3. Model explanation: a statement of why the fair value, rating, DCF, reverse DCF or scenario is what it is
   must match the valuation method in the facts. The fair value is a mechanical blend of the listed methods; it
   does not "reflect caution", "weigh weak cash flow" or "price in" a risk unless the facts say that input is
   in it. The reverse DCF's implied growth and implied margin are alternatives, not one joint scenario.
4. Like-for-like: TTM vs fiscal-year multiples, one period's growth vs a multi-year CAGR, year-on-year vs
   versus-a-peak, company vs peer median, trading vs reporting currency.
5. Caveat: if the claim relies on a figure the facts attach a caveat to (P/E basis, approximate history,
   withheld DCF, rating changed since the last report, one-off gains), the caveat must not be dropped.
6. Balance sheet and funding: claims about funding, leverage, debt or net cash must match the latest balance
   sheet (a rise in debt or fall in net cash contradicts "internally funded" / "no reliance on debt").
7. Recency and attribution: "recent", "latest", "brokers expect", "consensus" must match the dates and who
   said it; broker views are attributed, not stated as fact. Who acts must match the source: a company's own
   instruction or policy is not a government rule, and a report by one outlet is not a confirmed fact. A
   qualifier in the source ("certain", "up to", "may") must not be dropped.
A claim is ok if the sources support it, even if it is not how you would put it. Do not flag style."""


class ClaimVerdict(BaseModel):
    n: int = Field(description="The claim's number")
    verdict: Literal["ok", "wrong", "unsupported", "misleading"]
    check: int = Field(description="The checklist question (1-7) that fails; 0 if ok")
    problem: str = Field(description="What is wrong, in one sentence; empty if ok")
    evidence: str = Field(description="Exact words from the sources that show it (copied); empty if ok or if "
                                      "the problem is that no source states it")
    fix: str = Field(description="How to rewrite the sentence so it is true; empty if ok")
    support: str = Field("", description="If the claim states a cause or explains the model and you judge it "
                                         "ok: the exact source words that state that cause or explanation "
                                         "(copied); empty otherwise")


class CheckClaims(dspy.Signature):
    __doc__ = """You are the fact-checker of an equity research firm. You check single sentences from a draft
    report, one at a time, against the sources the writer was given. You do not see the rest of the draft:
    judge each claim only on what the sources say.

    """ + CHECKLIST + """

    For a claim that states a cause ("as", "because", "driven by", "reflecting" ...) or explains the model, an
    "ok" verdict needs `support`: the source words that state that same cause or explanation. If you cannot
    copy such words from the sources, the claim is "unsupported".

    Return one verdict per claim number. "wrong": the sources contradict it. "unsupported": it asserts a cause,
    trend or explanation no source gives. "misleading": true in words but drops a caveat or compares unlike
    things. Copy evidence verbatim from the sources."""
    sources: str = dspy.InputField(desc="Facts computed in code, research notes, news and filing excerpts")
    company: str = dspy.InputField()
    claims: str = dspy.InputField(desc="Numbered claims: [n] (section) sentence")
    verdicts: list[ClaimVerdict] = dspy.OutputField()


# ---------------------------------------------------------------- candidate claims (code)
# Run 2: time words used as a cause on the balance sheet ("net cash fell from $41.2bn after $39.0bn of buybacks",
# run 1, while debt had risen by $25bn): "after", "following", "on the back of", "thanks to" count as a stated cause
# when the sentence also has a balance-sheet word. Definitional uses ("cash flow after capex", "the following year")
# are not causes.
_TIME_WORD = (r"(?:\bafter\b(?![- ](?:tax|capex|capital|interest|deduct\w*|subtract\w*|minorit\w*|dividends? paid))|"
              r"(?<!\bthe )\bfollowing\b(?! (?:years?|quarters?|periods?|months?|table)\b)|\bon the back of\b|"
              r"\bthanks to\b)")
_BALANCE_WORD = r"\b(?:net cash|net debt|debt|cash|buy-?backs?|repurchas\w*)\b"
_TIME_CAUSE = rf"{_TIME_WORD}(?=.*?{_BALANCE_WORD})|{_BALANCE_WORD}(?=.*?{_TIME_WORD})"
_RISKY = re.compile(
    r"\b(as|because|due to|driven by|reflect\w*|amid|thanks to|owing to|led by|on the back of|caused|"
    r"accelerat\w*|decelerat\w*|slow\w*|re-?accelerat\w*|improv\w*|deteriorat\w*|weaken\w*|strengthen\w*|"
    r"rose|rise[sn]?|rising|fell|fall(?:s|ing|en)?|declin\w*|expand\w*|contract\w*|compress\w*|peak\w*|"
    r"cheap\w*|expensive|premium|discount|undervalued|overvalued|above|below|exceed\w*|lags?|"
    r"fair value|rating|dcf|reverse dcf|implies|implied|priced in|prices in|weigh\w*|caution|"
    r"funded|debt|net cash|leverage|borrow\w*|sentiment|consensus|brokers?|recent(?:ly)?|latest|"
    r"guid\w*|expects?|outlook)\b|" + _TIME_CAUSE, re.IGNORECASE | re.DOTALL)
# A stated cause (the most common reviewer finding): "because", "driven by", "as lithium prices rose" ...
_CAUSAL = re.compile(
    r"\b(because|due to|driven by|reflect(?:s|ing|ed)?|amid|thanks to|owing to|on the back of|caused by|"
    r"as a result of|led by|attributable to|fuell?ed by|helped by|hurt by|weighed on by)\b|"
    r"\bas (?:[\w-]+ ){0,5}(?:rose|fell|rise|fall|increased|decreased|declined|climbed|dropped|weakened|"
    r"strengthened|surged|slumped|grew|shrank|eased|jumped|slid)\b|" + _TIME_CAUSE, re.IGNORECASE | re.DOTALL)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
MAX_CLAIMS, BATCH = 48, 4


def sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n+", text or ""):
        para = para.strip().lstrip("-•* ").strip()
        out += [s.strip() for s in _SENT.split(para) if len(s.strip()) >= 25]
    return out


def candidates(parts: dict[str, str], limit: int = MAX_CLAIMS) -> list[tuple[str, str]]:
    """(section, sentence) pairs worth checking, page-1 sections first, de-duplicated."""
    order = ["tagline", "thesis", "key_takeaways", "rating_rationale", "variant_view", "pre_mortem", "risks",
             "catalysts", "financial_analysis", "valuation_overview", "report_summary", "competitive_analysis",
             "news_summary", "company_overview", "dupont_commentary", "comps_commentary", "events_to_monitor"]
    keys = [k for k in order if k in parts] + [k for k in parts if k not in order]
    seen, out = set(), []
    for k in keys:
        for s in sentences(parts.get(k) or ""):
            key = re.sub(r"\W+", " ", s.lower()).strip()
            if key in seen or not _RISKY.search(s):
                continue
            seen.add(key)
            out.append((k, s))
    return out[:limit]


# ---------------------------------------------------------------- verification of the checker (code)
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%.一-鿿]+", " ", (s or "").lower()).strip()


def evidence_ok(evidence: str, sources_norm: str) -> bool:
    """The cited evidence is in the sources (each part split at ellipses, 12+ characters)."""
    parts = [_norm(p) for p in re.split(r"\.\.\.|…", evidence or "")]
    parts = [p for p in parts if len(p) >= 12]
    return bool(parts) and all(p in sources_norm for p in parts)


def check(parts: dict[str, str], sources: str, company: str, lm: dspy.LM, adapter,
          limit: Optional[int] = None) -> tuple[list[ReviewNote], dict]:
    """Check the risky claims of a draft (at most ``limit``, default CLAIM_CHECK_LIMIT). Returns review notes
    (same shape as the deep reviewer's) and stats."""
    from ..config import settings
    claims = candidates(parts, limit or settings.claim_check_limit)
    stats = {"claims": len(claims), "calls": 0, "flagged": 0, "kept": 0, "no_evidence": 0, "cause_unbacked": 0,
             "failed_batches": 0}
    if not claims:
        return [], stats
    batches = [claims[i:i + BATCH] for i in range(0, len(claims), BATCH)]

    def one(batch: list[tuple[str, str]], offset: int):
        text = "\n".join(f"[{offset + j + 1}] ({sec}) {s}" for j, (sec, s) in enumerate(batch))
        # A failed batch leaves its sentences unchecked, so it is retried once (a fresh call: rollout_id skips
        # DSPy's cache of the failed answer) before giving up.
        for attempt in range(2):
            try:
                with dspy.context(lm=lm, adapter=adapter):
                    out = dspy.Predict(CheckClaims)(sources=sources, company=company, claims=text,
                                                    **({"config": {"rollout_id": attempt}} if attempt else {}))
                return list(out.verdicts or [])
            except Exception as e:
                log.warning("claim check batch %d failed (attempt %d): %s", offset // BATCH + 1, attempt + 1,
                            type(e).__name__)
        stats["failed_batches"] += 1
        return []

    # The first batch runs alone, so the provider caches the shared prefix (instructions + sources) before the
    # others are sent together; sent all at once, every call paid the full input price (9 Nov 2026).
    verdicts = one(batches[0], 0)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [provenance.submit(pool, one, b, i * BATCH) for i, b in enumerate(batches) if i]
        verdicts += [v for f in futs for v in f.result()]
    stats["calls"] = len(batches)
    src_norm = _norm(sources)
    notes, seen = [], set()
    for v in verdicts:
        if not (1 <= v.n <= len(claims)) or v.n in seen:
            continue
        section, sentence = claims[v.n - 1]
        if v.verdict == "ok":
            # a cause judged "ok" must be backed by source words that really exist (checked here, not trusted)
            if not (_CAUSAL.search(sentence) and not evidence_ok(v.support, src_norm)):
                continue
            stats["cause_unbacked"] += 1
            v = ClaimVerdict(n=v.n, verdict="unsupported", check=2,
                             problem="It states a cause, and no source sentence that states this cause was found.",
                             evidence="", fix="Remove the cause, or attribute it to the source that states it.")
        stats["flagged"] += 1
        # "wrong" and "misleading" must show their evidence; "unsupported" means no source states the claim
        if v.verdict in ("wrong", "misleading") and not evidence_ok(v.evidence, src_norm):
            stats["no_evidence"] += 1
            continue
        seen.add(v.n)
        ev = f' Evidence: "{v.evidence.strip()}"' if v.evidence and v.evidence.strip() else ""
        notes.append(ReviewNote(section=section, quote=sentence[:300],
                                problem=f"{v.verdict} (check {v.check}): {v.problem.strip()}{ev}",
                                fix=(v.fix or "").strip() or "Rewrite or remove the sentence."))
    stats["kept"] = len(notes)
    return notes, stats


def sources_text(facts: str, news: str, filings: str, extra: Optional[str] = None) -> str:
    parts = [f"FACTS (computed in code):\n{facts}", f"NEWS:\n{news or 'None'}", f"FILING EXCERPTS:\n{filings or 'None'}"]
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)
