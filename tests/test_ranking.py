import logging

import pytest

from app.services import ranking

USER_INPUT = {"methodology": "m", "organism": "o", "tissue": "t"}


def _cands(n):
    return [{"accession": f"GSE{i}", "title": "t", "ftp_link": "ftp://x"} for i in range(n)]


def _verdict(acc, relevant=True, confidence="high", meets=True):
    return {"accession": acc, "relevant": relevant, "confidence": confidence,
            "meets_data_availability": meets, "matched_conditions": [], "match_summary": "s"}


@pytest.fixture
def judge(monkeypatch):
    """Stub the OpenAI call: records batches, marks every candidate relevant/high."""
    seen = []

    def fake(user_input, batch):
        seen.append([c["accession"] for c in batch])
        return [_verdict(c["accession"]) for c in batch]

    monkeypatch.setattr(ranking, "_judge_batch", fake)
    monkeypatch.setattr(ranking, "RANKING_BATCH_SIZE", 20)
    return seen


def test_candidates_are_split_into_batches_covering_all(judge):
    out = ranking.rank_candidates(USER_INPUT, _cands(45))
    assert sorted(len(b) for b in judge) == [5, 20, 20]
    assert sorted(v["accession"] for v in out) == sorted(f"GSE{i}" for i in range(45))


def test_empty_input_makes_no_calls(judge):
    assert ranking.rank_candidates(USER_INPUT, []) == []
    assert judge == []


def test_irrelevant_verdicts_are_filtered_out(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict("GSE1"), _verdict("GSE2", relevant=False)])
    out = ranking.rank_candidates(USER_INPUT, _cands(2))
    assert [v["accession"] for v in out] == ["GSE1"]


def test_sorted_by_confidence_then_data_availability_keeping_ncbi_order(monkeypatch):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [
        _verdict("A", confidence="medium", meets=True),
        _verdict("B", confidence="high", meets=False),
        _verdict("C", confidence=" HIGH ", meets=True),   # casing/whitespace tolerated
        _verdict("D", confidence="medium", meets=True),
        _verdict("E", confidence="bogus", meets=True),    # unknown label sorts last
    ])
    out = ranking.rank_candidates(USER_INPUT, _cands(5))
    assert [v["accession"] for v in out] == ["C", "B", "A", "D", "E"]


def test_short_coverage_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(ranking, "_judge_batch", lambda u, b: [_verdict(b[0]["accession"])])
    with caplog.at_level(logging.WARNING, logger="app.services.ranking"):
        ranking.rank_candidates(USER_INPUT, _cands(5))
    assert "covered 1 of 5" in caplog.text


def test_openai_errors_propagate(monkeypatch):
    import openai

    def boom(u, b):
        raise openai.OpenAIError("down")

    monkeypatch.setattr(ranking, "_judge_batch", boom)
    with pytest.raises(openai.OpenAIError):
        ranking.rank_candidates(USER_INPUT, _cands(3))


def test_links_are_not_sent_to_the_model():
    assert "ftp_link" not in ranking._slim({"accession": "GSE1", "ftp_link": "ftp://x"})
