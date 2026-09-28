"""Standalone prototype validating the core Seq2Find search flow.

Fetches a candidate set of GEO series live from NCBI, then asks an LLM to
rank/filter them against a biologist's full input -- including free-text
criteria that aren't structured GEO fields, like "TLS annotations present".

Run directly: `python prototype/search_prototype.py`

No auth, database, or API endpoint involved yet -- this only proves out the
search logic itself before it's wired into the real backend.
"""

import json
import os
import time

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "seq2find@example.com")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")
# NCBI caps unauthenticated E-utilities calls at 3 req/sec (10/sec with a key).
# Multiple query variants per search means several calls back-to-back, so we
# throttle client-side rather than rely on NCBI to just accept the burst.
NCBI_MIN_INTERVAL = 0.11 if NCBI_API_KEY else 0.35

OPENAI_MODEL = "gpt-4o-mini"
QUERY_VARIANT_COUNT = 3
# Merging several query variants' results can produce a large pool (69
# candidates from 3 variants in testing) -- cap what actually gets sent to
# the AI ranking step to bound token cost/latency per search.
MAX_CANDIDATES_FOR_RANKING = 40

EXAMPLE_INPUT = {
    "methodology": "Spatial single-cell RNA-seq",
    "organism": "Human",
    "tissue": "Pancreatic tissue",
    "conditions": [
        "PDAC primary resection, treatment-naive",
        "Healthy patient pancreas (control)",
        "PDAC primary resection, GEM (gemcitabine) treatment",
    ],
    "data_availability": "Metadata must indicate TLS (tertiary lymphoid structure) annotations present",
}


def _ncbi_params(extra: dict) -> dict:
    params = {"tool": "seq2find", "email": NCBI_EMAIL, "retmode": "json", **extra}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


_last_ncbi_request = 0.0


def _ncbi_get(path: str, params: dict) -> dict:
    global _last_ncbi_request
    for attempt in range(3):
        wait = NCBI_MIN_INTERVAL - (time.monotonic() - _last_ncbi_request)
        if wait > 0:
            time.sleep(wait)
        resp = requests.get(f"{NCBI_BASE}/{path}", params=_ncbi_params(params), timeout=15)
        _last_ncbi_request = time.monotonic()
        if resp.status_code == 429:
            time.sleep(1 + attempt)  # backoff and retry -- shared NCBI limit, not our own bug
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def build_geo_query(user_input: dict) -> str:
    # Keyword-match only the "hard" structural fields (methodology, organism,
    # tissue). Conditions and data-availability nuance (e.g. "TLS annotations
    # present") rarely appear as literal matchable text across all candidates,
    # so those are left for the AI ranking step rather than the search term.
    # Terms are left unquoted so NCBI's own MeSH/synonym expansion applies --
    # quoting them as exact phrases was tested and cut recall drastically.
    terms = [user_input["methodology"], user_input["organism"], user_input["tissue"]]
    return " AND ".join(terms)


def generate_query_variants(user_input: dict, n: int = QUERY_VARIANT_COUNT) -> list[str]:
    """Ask the LLM for alternate NCBI search phrasings.

    GEO submitters describe the same study in different words (e.g. "spatial
    transcriptomics" vs "spatial single-cell RNA-seq" vs "Visium spatial gene
    expression"), so a single literal query misses real matches -- confirmed
    while testing this: a strong match for the PDAC example only surfaced
    once "spatial transcriptomics" was tried as an alternate phrasing to the
    user's literal "Spatial single-cell RNA-seq". This asks the model to
    propose a few equivalent phrasings, not to interpret full study text.
    """
    client = OpenAI()
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Given a biologist's structured search criteria for GEO "
                    "study data, propose alternate short NCBI search-term "
                    "phrasings combining the methodology, organism, and "
                    "tissue/cell type using different but scientifically "
                    "equivalent wording GEO submitters might use (synonyms, "
                    "abbreviations, related assay names). Return JSON: "
                    f'{{"queries": [str, ...]}} with up to {n} short query '
                    "strings, each combining all three fields."
                ),
            },
            {"role": "user", "content": json.dumps(user_input)},
        ],
    )
    variants = json.loads(response.choices[0].message.content)["queries"]
    return [build_geo_query(user_input)] + variants[:n]


def fetch_candidates(query: str, retmax: int = 40) -> list[dict]:
    search_json = _ncbi_get("esearch.fcgi", {"db": "gds", "term": query, "retmax": retmax})
    ids = search_json["esearchresult"].get("idlist", [])
    if not ids:
        return []

    summary_json = _ncbi_get("esummary.fcgi", {"db": "gds", "id": ",".join(ids)})
    result = summary_json["result"]

    candidates = []
    for uid in result["uids"]:
        record = result[uid]
        if record.get("entrytype") != "GSE":
            continue
        candidates.append(
            {
                "accession": record["accession"],
                "title": record["title"],
                "summary": record["summary"],
                "organism": record["taxon"],
                "n_samples": record["n_samples"],
                "supplementary_files": record["suppfile"],
                "ftp_link": record["ftplink"],
            }
        )
    return candidates


def rank_with_ai(user_input: dict, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    client = OpenAI()
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are ranking GEO study records against a biologist's search "
                    "criteria. Only include candidates that plausibly match the "
                    "methodology, organism, and tissue, and note whether each "
                    "candidate's title/summary supports the requested conditions "
                    "and data-availability requirement. Return JSON: "
                    '{"results": [{"accession": str, "match_summary": str, '
                    '"matched_conditions": [str], "meets_data_availability": bool, '
                    '"confidence": "high"|"medium"|"low"}]}, best matches first. '
                    "Exclude candidates that clearly don't match."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"search_criteria": user_input, "candidates": candidates}
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)["results"]


def search(user_input: dict) -> list[dict]:
    queries = generate_query_variants(user_input)
    candidates_by_accession: dict[str, dict] = {}
    for query in queries:
        for candidate in fetch_candidates(query):
            candidates_by_accession.setdefault(candidate["accession"], candidate)
    # Insertion order approximates combined relevance: each fetch_candidates
    # call returns NCBI's own relevance-sorted order, and the literal query
    # (closest to the user's actual input) runs first.
    merged = list(candidates_by_accession.values())[:MAX_CANDIDATES_FOR_RANKING]
    return rank_with_ai(user_input, merged)


if __name__ == "__main__":
    ranked_results = search(EXAMPLE_INPUT)
    print(json.dumps(ranked_results, indent=2))
