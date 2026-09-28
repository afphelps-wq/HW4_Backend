"""AI ranking of GEO candidates against a biologist's full search criteria.

Candidates are judged in small batches, one verdict required per candidate.
Asking one call to pick the good ones out of ~100 made the model skim and
skip most of them; small batches with a mandatory per-candidate verdict gave
full coverage in testing (see RANKING_BATCH_SIZE in app.config).
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from app.config import RANKING_BATCH_SIZE, RANKING_MODEL

log = logging.getLogger(__name__)

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_MAX_PARALLEL_BATCHES = 5

_SYSTEM_PROMPT = (
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


def _slim(candidate: dict) -> dict:
    # Links aren't needed to judge a study; leaving them out saves tokens.
    return {k: v for k, v in candidate.items() if k != "ftp_link"}


def _judge_batch(user_input: dict, batch: list[dict]) -> list[dict]:
    """One OpenAI call: a verdict dict per candidate in `batch`."""
    response = OpenAI().chat.completions.create(
        model=RANKING_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"search_criteria": user_input, "candidates": [_slim(c) for c in batch]}
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)["verdicts"]


def rank_candidates(user_input: dict, candidates: list[dict]) -> list[dict]:
    """Return the relevant candidates' verdicts, best first.

    Sorted by confidence, then by whether the data-availability requirement is
    met; ties keep NCBI's relevance order. Any OpenAI error propagates.
    """
    if not candidates:
        return []
    size = RANKING_BATCH_SIZE
    batches = [candidates[i : i + size] for i in range(0, len(candidates), size)]
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_BATCHES) as pool:
        judged = list(pool.map(lambda b: _judge_batch(user_input, b), batches))

    verdict_count = sum(len(v) for v in judged)
    if verdict_count != len(candidates):
        log.warning("Ranker covered %d of %d candidates", verdict_count, len(candidates))

    relevant = [v for verdicts in judged for v in verdicts if v.get("relevant")]
    relevant.sort(
        key=lambda v: (
            _CONFIDENCE_ORDER.get(str(v.get("confidence", "low")).strip().lower(), 2),
            not v.get("meets_data_availability"),
        )
    )
    return relevant
