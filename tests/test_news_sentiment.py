from agente_bolsa.tools.news_sentiment import assess_material_news_risk


def test_assess_material_news_risk_flags_competitive_threat_without_llm():
    risk = assess_material_news_risk(
        "FDX",
        [
            {
                "title": "FedEx slides as Amazon logistics expands third-party delivery",
                "summary": "The rival service adds margin pressure for parcel carriers.",
            }
        ],
        {"risk_flags": ["sentiment_failed"]},
    )

    assert risk["material"] is True
    assert risk["severity"] == "material"
    assert "amazon logistics" in risk["matched_terms"]
