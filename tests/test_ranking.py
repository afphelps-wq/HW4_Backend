import logging

import openai
import pytest

from app.services import ranking

USER_INPUT = {"methodology": "m", "organism": "o", "tissue": "t",
              "data_availability": "TLS annotations present"}


def _cands(n):
    return [{"accession": f"GSE{i}", "title": f"Study {i}", "summary": f"summary {i}",
             "ftp_link": "ftp://x"} for i in range(n)]


def _verdict(acc, relevant=True, confidence="high", meets=True, evidence=""):
    return {"accession": acc, "relevant": relevant, "confidence": confidence,
            "meets_data_availability": meets, "matched_conditions": [],
            "match_summary": "s", "evidence": evidence}


@pytest.fixture(autouse=True)
def small_batches(monkeypatch):
    monkeypatch.setattr(ranking, "RANKING_BATCH_SIZE", 20)


@pytest.fixture
def judge(monkeypatch):
    """Stub stage 1: records batches, marks every candidate relevant/high."""
    seen = []

    def fake(user_input, batch):
        seen.append([c["accession"] for c in batch])
        return [_verdict(c["accession"]) for c in batch]

    monkeypatch.setattr(ranking, "_judge_batch", fake)
    return seen


# ---- stage 1 -------------------------------------------------------------

def test_candidates_are_split_into_batches_covering_all(judge):
    out = ranking._stage1(USER_INPUT, _cands(45))
    assert sorted(len(b) for b in judge) == [5, 20, 20]
    assert sorted(v["accession"] for v in out) == sorted(f"GSE{i}" for i in range(45))


def test_irrelevant_verdicts_are_filtered_out(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict("GSE0"), _verdict("GSE1", relevant=False)])
    assert [v["accession"] for v in ranking._stage1(USER_INPUT, _cands(2))] == ["GSE0"]


def test_stage1_sorts_by_confidence_tolerating_casing(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict("GSE0", confidence="medium"),
        _verdict("GSE1", confidence=" HIGH "),
        _verdict("GSE2", confidence="bogus"),
    ])
    assert [v["accession"] for v in ranking._stage1(USER_INPUT, _cands(3))] == ["GSE1", "GSE0", "GSE2"]


def test_skipped_candidates_are_retried_once(monkeypatch):
    calls = []

    def fake(user_input, batch):
        accs = [c["accession"] for c in batch]
        calls.append(accs)
        # first pass skips GSE3 and GSE4; the retry answers everything asked
        return [_verdict(a) for a in accs if len(calls) > 1 or a not in ("GSE3", "GSE4")]

    monkeypatch.setattr(ranking, "_judge_batch", fake)
    out = ranking._stage1(USER_INPUT, _cands(5))
    assert calls[1] == ["GSE3", "GSE4"]
    assert len(out) == 5


def test_candidates_still_skipped_after_retry_are_logged(monkeypatch, caplog):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [_verdict(b[0]["accession"])])
    with caplog.at_level(logging.WARNING, logger="app.services.ranking"):
        out = ranking._stage1(USER_INPUT, _cands(5))
    assert "still skipped 4 of 5" in caplog.text or "still skipped 3 of 5" in caplog.text
    assert len(out) == 2  # one from the first pass, one from the retry


def test_invented_and_duplicate_verdicts_are_ignored(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict("GSE0", confidence="low"), _verdict("GSE0", confidence="high"),
        _verdict("GSE_FAKE")])
    out = ranking._stage1(USER_INPUT, _cands(1))
    assert [(v["accession"], v["confidence"]) for v in out] == [("GSE0", "low")]


def test_links_are_not_sent_to_the_model():
    assert "ftp_link" not in ranking._slim({"accession": "GSE1", "ftp_link": "ftp://x"})


# ---- stage 2 -------------------------------------------------------------

def _run(monkeypatch, cands, ranked, terms=("TLS",), user_input=USER_INPUT):
    monkeypatch.setattr(ranking, "_judge_batch",
                        lambda u, b: [_verdict(c["accession"]) for c in b])
    monkeypatch.setattr(ranking, "_final_rank",
                        lambda u, c: {"requirement_terms": list(terms), "ranked": ranked})
    return ranking.rank_candidates(user_input, cands)


def test_availability_needs_model_judgment_and_a_term_in_the_text(monkeypatch):
    cands = _cands(4)
    cands[0]["summary"] = "We map TLS regions across samples."      # term present
    cands[1]["summary"] = "Nothing relevant here."                  # term absent
    cands[2]["summary"] = "Mentions TLS only in passing."           # term present, model says no
    cands[3]["summary"] = "Tertiary lymphoid structures were found."  # term present, plural/other term
    ranked = [
        _verdict("GSE0", meets=True), _verdict("GSE1", meets=True),
        _verdict("GSE2", meets=False), _verdict("GSE3", meets=True),
    ]
    out = {i["accession"]: i for i in _run(monkeypatch, cands, ranked,
                                            terms=("TLS", "tertiary lymphoid structure"))}
    assert out["GSE0"]["meets_data_availability"] is True
    assert "TLS regions" in out["GSE0"]["evidence"]
    assert out["GSE1"]["meets_data_availability"] is False and out["GSE1"]["evidence"] == ""
    assert out["GSE2"]["meets_data_availability"] is False
    assert out["GSE3"]["meets_data_availability"] is True          # "structure" matches "structures"


def test_evidence_is_cut_from_the_source_text_with_context(monkeypatch):
    cands = _cands(1)
    long = "x" * 200
    cands[0]["summary"] = f"{long} intratumoral TLS\x03associated B-cell maturation {long}"
    out = _run(monkeypatch, cands, [_verdict("GSE0")], terms=("TLS-associated",))
    ev = out[0]["evidence"]
    assert "TLS associated B-cell" in ev            # control char normalized to a space
    assert ev.startswith("...") and ev.endswith("...")
    assert len(ev) < 220


def test_no_usable_terms_fails_closed_and_warns(monkeypatch, caplog):
    cands = _cands(2)
    with caplog.at_level(logging.WARNING, logger="app.services.ranking"):
        out = _run(monkeypatch, cands, [_verdict("GSE0"), _verdict("GSE1")], terms=("", "a"))
    assert not any(i["meets_data_availability"] for i in out)
    assert "no usable search terms" in caplog.text


def test_candidates_meeting_the_requirement_rank_first(monkeypatch):
    cands = _cands(3)
    cands[2]["title"] = "has tls annotations"
    ranked = [
        _verdict("GSE0", confidence="high", meets=False),
        _verdict("GSE1", confidence="high", meets=False),
        _verdict("GSE2", confidence="low", meets=True),
    ]
    out = _run(monkeypatch, cands, ranked)
    assert [i["accession"] for i in out] == ["GSE2", "GSE0", "GSE1"]


def test_no_requirement_means_availability_is_trivially_met(monkeypatch):
    ui = {**USER_INPUT, "data_availability": ""}
    out = _run(monkeypatch, _cands(2), [_verdict("GSE0", meets=False), _verdict("GSE1", meets=False)],
               terms=(), user_input=ui)
    assert all(i["meets_data_availability"] for i in out)


def test_stage2_drops_irrelevant_unknown_and_duplicate_items(monkeypatch):
    ranked = [_verdict("GSE0"), _verdict("GSE1", relevant=False),
              _verdict("GSE_FAKE"), _verdict("GSE0", confidence="low")]
    out = _run(monkeypatch, _cands(2), ranked, terms=(),
               user_input={**USER_INPUT, "data_availability": ""})
    assert [i["accession"] for i in out] == ["GSE0"]


def test_only_stage1_survivors_reach_stage2_and_are_capped(monkeypatch):
    monkeypatch.setattr(ranking, "RERANK_MAX_CANDIDATES", 3)
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict(c["accession"], relevant=c["accession"] != "GSE1") for c in b])
    sent = {}

    def capture(u, c):
        sent["acc"] = [x["accession"] for x in c]
        return {"requirement_terms": [], "ranked": []}

    monkeypatch.setattr(ranking, "_final_rank", capture)
    ranking.rank_candidates(USER_INPUT, _cands(6))
    assert sent["acc"] == ["GSE0", "GSE2", "GSE3"]  # GSE1 filtered; capped at 3


def test_no_survivors_skips_stage2(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch",
                        lambda u, b: [_verdict(c["accession"], relevant=False) for c in b])

    def never(u, c):
        raise AssertionError("stage 2 should not run")

    monkeypatch.setattr(ranking, "_final_rank", never)
    assert ranking.rank_candidates(USER_INPUT, _cands(3)) == []
    assert ranking.rank_candidates(USER_INPUT, []) == []


def test_openai_errors_propagate(monkeypatch):
    def boom(u, b):
        raise openai.OpenAIError("down")

    monkeypatch.setattr(ranking, "_judge_batch", boom)
    with pytest.raises(openai.OpenAIError):
        ranking.rank_candidates(USER_INPUT, _cands(3))
