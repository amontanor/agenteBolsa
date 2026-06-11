"""Tests de diversidad del comite (T5.11)."""

from agente_bolsa.tools.committee_diversity import (
    buy_requires_deterministic_candidate,
    model_id_from_llm_result,
    vote_correlation,
    votes_by_model,
)


def test_vote_correlation_flags_redundant_pair():
    # Dos modelos identicos en 60 dictamenes -> redundantes; uno distinto -> no.
    a = ["buy"] * 30 + ["hold"] * 30
    b = list(a)  # identico
    c = ["sell"] * 60  # opuesto
    result = vote_correlation({"modelA": a, "modelB": b, "modelC": c})
    pair_ab = next(p for p in result["pairs"] if {p["a"], p["b"]} == {"modelA", "modelB"})
    pair_ac = next(p for p in result["pairs"] if {p["a"], p["b"]} == {"modelA", "modelC"})
    assert pair_ab["agreement"] == 1.0 and pair_ab["redundant"] is True
    assert pair_ac["redundant"] is False
    assert len(result["redundant_pairs"]) == 1


def test_small_sample_not_flagged_even_if_identical():
    a = ["buy"] * 10
    b = ["buy"] * 10
    result = vote_correlation({"m1": a, "m2": b})
    assert result["pairs"][0]["agreement"] == 1.0
    assert result["pairs"][0]["redundant"] is False  # n<50


def test_model_id_extraction_and_grouping():
    assert model_id_from_llm_result({"model": "gemini-3.5-flash"}) == "gemini-3.5-flash"
    assert model_id_from_llm_result({"endpoint": {"model": "mimo-deep"}}) == "mimo-deep"
    assert model_id_from_llm_result({}) is None

    decisions = [
        {"llm": {"model": "gemini"}, "vote": "buy"},
        {"llm": {"model": "gemini"}, "vote": "hold"},
        {"llm": {"model": "mimo"}, "vote": "buy"},
    ]
    grouped = votes_by_model(decisions)
    assert grouped == {"gemini": ["buy", "hold"], "mimo": ["buy"]}


def test_buy_invariant_requires_deterministic_candidate():
    recs = [
        {"symbol": "AAPL", "action": "buy"},
        {"symbol": "MSFT", "action": "hold"},
        {"symbol": "NVDA", "action": "buy"},
    ]
    ok, offenders = buy_requires_deterministic_candidate(recs, {"AAPL", "NVDA"})
    assert ok and offenders == []

    ok2, offenders2 = buy_requires_deterministic_candidate(recs, {"AAPL"})
    assert not ok2 and offenders2 == ["NVDA"]  # NVDA comprada sin candidato
