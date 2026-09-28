"""AI ranking of GEO candidates against a biologist's full search criteria.

Two stages:

1. Filter: candidates are judged in small batches, one verdict required per
   candidate, keeping the plausibly relevant ones. Asking one call to pick the
   good ones out of ~100 made the model skim and skip most of them; small
   batches with a mandatory verdict gave full coverage in testing. Candidates
   the model still skips are retried once.
2. Re-rank: one call over the survivors ranks them against each other (batch
   verdicts aren't comparable across batches -- nearly everything came back
   "high") and judges the data-availability requirement strictly: it may only
   say the requirement is met if the model judges so AND one of the search terms
   it proposed for the requirement (once per search, e.g. "TLS") literally
   appears in the study's title/summary; the evidence snippet is cut from that
   text by code, so it can't be invented.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from app.config import (
    RANKING_BATCH_SIZE,
    RANKING_MODEL,
    RERANK_MAX_CANDIDATES,
    RERANK_MODEL,
)

log = logging.getLogger(__name__)

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_MAX_PARALLEL_BATCHES = 5

_FILTER_PROMPT = (
    "You are judging GEO study records against a biologist's search criteria. "
    "You MUST return exactly one entry for EVERY candidate, in the same order, "
    "never skipping any. Return JSON: {\"verdicts\": [{\"accession\": str, "
    "\"relevant\": bool, \"confidence\": \"high\"|\"medium\"|\"low\", "
    "\"meets_data_availability\": bool, \"matched_conditions\": [str], "
    "\"match_summary\": str}]}. relevant=true only if the candidate plausibly "
    "matches the methodology, organism and tissue. meets_data_availability is "
    "true only if the title/summary supports the data-availability requirement. "
    "Keep match_summary to one sentence, and leave it empty when relevant=false."
)

_RERANK_PROMPT = (
    "You are the final ranker for a search over GEO study records. Every "
    "candidate below already passed a first relevance filter. Rank them "
    "best-first against the biologist's criteria and return JSON: "
    "{\"requirement_terms\": [str], \"ranked\": [{\"accession\": str, "
    "\"relevant\": bool, \"confidence\": \"high\"|\"medium\"|\"low\", "
    "\"meets_data_availability\": bool, \"matched_conditions\": [str], "
    "\"match_summary\": str}]}. Return one ranked entry per candidate. Rules:\n"
    "- requirement_terms: if the criteria include a data-availability "
    "requirement, list 2-6 literal words, abbreviations or synonyms that a "
    "study's title or summary would contain if it satisfied that requirement "
    "(for a requirement like 'sample metadata must include batch labels' you "
    "might return [\"batch\", \"batch label\"]). Use [] if there is no requirement.\n"
    "- Confidence must be comparable across the whole list. Use \"high\" only for "
    "candidates that fit the methodology, organism and tissue AND meaningfully "
    "fit the requested conditions and data-availability requirement. Most "
    "candidates should NOT be high.\n"
    "- meets_data_availability is true ONLY if the candidate's title or summary "
    "explicitly states the requirement. Do not infer it from the topic alone.\n"
    "- matched_conditions lists only conditions the text actually supports; "
    "leave it empty if none are supported.\n"
    "- Set relevant=false ONLY for candidates that clearly do not fit the "
    "methodology, organism or tissue. Do not drop a candidate just because it "
    "lacks the data-availability requirement or some conditions; keep it and "
    "rank it lower with a lower confidence.\n"
    "- match_summary is one sentence explaining the fit."
)


def _slim(candidate: dict) -> dict:
    # Links aren't needed to judge a study; leaving them out saves tokens.
    return {k: v for k, v in candidate.items() if k != "ftp_link"}


def _judge_batch(user_input: dict, batch: list[dict]) -> list[dict]:
    """Stage 1, one OpenAI call: a verdict dict per candidate in `batch`."""
    response = OpenAI().chat.completions.create(
        model=RANKING_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _FILTER_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"search_criteria": user_input, "candidates": [_slim(c) for c in batch]}
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)["verdicts"]


def _final_rank(user_input: dict, candidates: list[dict]) -> dict:
    """Stage 2, one OpenAI call over the stage-1 survivors.

    Returns {"requirement_terms": [...], "ranked": [...]}."""
    response = OpenAI().chat.completions.create(
        model=RERANK_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _RERANK_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"search_criteria": user_input, "candidates": [_slim(c) for c in candidates]}
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)


def _judge_in_batches(user_input: dict, candidates: list[dict]) -> list[dict]:
    size = RANKING_BATCH_SIZE
    batches = [candidates[i : i + size] for i in range(0, len(candidates), size)]
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_BATCHES) as pool:
        judged = pool.map(lambda b: _judge_batch(user_input, b), batches)
        return [v for verdicts in judged for v in verdicts]


def _confidence_rank(verdict: dict) -> int:
    return _CONFIDENCE_ORDER.get(str(verdict.get("confidence", "low")).strip().lower(), 2)


def _stage1(user_input: dict, candidates: list[dict]) -> list[dict]:
    """Verdicts for the plausibly relevant candidates, best first."""
    known = {c["accession"] for c in candidates}
    verdicts: dict[str, dict] = {}

    def collect(new: list[dict]) -> None:
        for v in new:
            acc = v.get("accession")
            if acc in known and acc not in verdicts:  # ignore invented/duplicate entries
                verdicts[acc] = v

    collect(_judge_in_batches(user_input, candidates))
    missing = [c for c in candidates if c["accession"] not in verdicts]
    if missing:
        log.info("Retrying %d candidates the ranker skipped", len(missing))
        collect(_judge_in_batches(user_input, missing))
        still = sum(1 for c in candidates if c["accession"] not in verdicts)
        if still:
            log.warning("Ranker still skipped %d of %d candidates", still, len(candidates))

    relevant = [v for v in verdicts.values() if v.get("relevant")]
    relevant.sort(key=_confidence_rank)
    return relevant


def _term_pattern(term: str) -> re.Pattern | None:
    """Case-insensitive pattern for a search term. Matches on word starts, so
    "structure" also finds "structures", and treats any run of non-alphanumeric
    characters as equal (NCBI text sometimes has stray control characters where
    a hyphen belongs)."""
    words = re.findall(r"[0-9A-Za-z]+", term)
    if not words or sum(len(w) for w in words) < 3:
        return None
    return re.compile(r"\b" + r"[^0-9A-Za-z]+".join(map(re.escape, words)), re.IGNORECASE)


def _evidence(text: str, patterns: list[re.Pattern]) -> str | None:
    """A snippet of `text` around the first search-term hit, or None."""
    hits = [m for p in patterns if (m := p.search(text))]
    if not hits:
        return None
    m = min(hits, key=lambda h: h.start())
    lo, hi = max(0, m.start() - 70), min(len(text), m.end() + 70)
    snippet = re.sub(r"[\x00-\x1f\s]+", " ", text[lo:hi]).strip()
    return f"{'...' if lo else ''}{snippet}{'...' if hi < len(text) else ''}"


def _stage2(user_input: dict, survivors: list[dict], by_acc: dict[str, dict]) -> list[dict]:
    """Re-rank stage-1 survivors; returns result items (with `evidence`)."""
    survivors = survivors[:RERANK_MAX_CANDIDATES]
    response = _final_rank(user_input, [by_acc[v["accession"]] for v in survivors])
    requirement = (user_input.get("data_availability") or "").strip()

    patterns = [
        p for t in response.get("requirement_terms") or [] if (p := _term_pattern(str(t)))
    ]
    if requirement and not patterns:
        log.warning("Re-ranker gave no usable search terms for the data-availability "
                    "requirement; treating it as unmet for every candidate")

    out, seen = [], set()
    for item in response.get("ranked", []):
        acc = item.get("accession")
        if acc not in by_acc or acc in seen or not item.get("relevant"):
            continue
        seen.add(acc)
        item = dict(item)
        item["evidence"] = ""
        if requirement:
            candidate = by_acc[acc]
            text = f"{candidate.get('title', '')}. {candidate.get('summary', '')}"
            snippet = _evidence(text, patterns)
            # The model's judgment AND a literal term hit in the study's own text.
            item["meets_data_availability"] = bool(item.get("meets_data_availability") and snippet)
            item["evidence"] = snippet if item["meets_data_availability"] else ""
        else:
            item["meets_data_availability"] = True  # nothing was required
        out.append(item)

    dropped = [v["accession"] for v in survivors if v["accession"] not in seen]
    log.info("Re-rank terms %s; kept %d of %d survivors; dropped/omitted: %s",
             response.get("requirement_terms"), len(out), len(survivors),
             ", ".join(dropped) or "none")

    # A stated data-availability requirement is a hard one, so candidates that
    # meet it go first; the re-ranker's order is kept within each group.
    if requirement:
        out.sort(key=lambda i: (not i["meets_data_availability"], _confidence_rank(i)))
    return out


def rank_candidates(user_input: dict, candidates: list[dict]) -> list[dict]:
    """Result items for the best candidates, best first. OpenAI errors propagate."""
    if not candidates:
        return []
    survivors = _stage1(user_input, candidates)
    log.info("Stage 1 kept %d of %d candidates", len(survivors), len(candidates))
    if not survivors:
        return []
    return _stage2(user_input, survivors, {c["accession"]: c for c in candidates})
