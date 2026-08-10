import pandas as pd

from agente_bolsa import web_app


def _portfolio_history():
    return {
        "timestamp": [
            "2026-08-05T00:00:00Z",
            "2026-08-06T00:00:00Z",
            "2026-08-07T00:00:00Z",
            "2026-08-10T00:00:00Z",
        ],
        "equity": [100.0, 101.0, 99.0, 99.0],
    }


def test_portfolio_series_exposes_signed_percent_label_and_color_for_each_point():
    frame = web_app._portfolio_value_series_from_alpaca(
        _portfolio_history(), current_equity=None, start_date="2026-08-01"
    )

    assert list(frame["label_pct"]) == ["n/d", "+1.00%", "-1.98%", "0.00%"]
    assert list(frame["label_color"]) == ["#374151", "#15803d", "#b91c1c", "#374151"]


def test_visible_window_keeps_percent_from_hidden_predecessor():
    frame = web_app._portfolio_value_series_from_alpaca(
        _portfolio_history(), current_equity=None, start_date="2026-08-01"
    )

    visible = web_app._trim_portfolio_chart_range(frame, days=3)

    assert list(visible["fecha"]) == ["2026-08-05", "2026-08-06", "2026-08-07"]
    assert list(visible["label_pct"]) == ["+1.00%", "-1.98%", "0.00%"]


def test_chart_adds_text_labels_without_changing_summary(monkeypatch):
    frame = web_app._portfolio_value_series_from_alpaca(
        _portfolio_history(), current_equity=None, start_date="2026-08-01"
    )
    captured = []
    monkeypatch.setattr(web_app.st, "altair_chart", lambda chart, **_: captured.append(chart))

    summary = web_app._portfolio_value_chart({}, None, days=None, equity_df=frame)

    assert summary["pl"] == -1.0
    assert summary["pl_pct"] == -0.01
    assert captured
    spec = captured[0].to_dict()
    text_layers = [layer for layer in spec["layer"] if layer.get("mark", {}).get("type") == "text"]
    assert len(text_layers) == 1
    assert text_layers[0]["encoding"]["text"]["field"] == "label_pct"


def test_chart_derives_safe_labels_for_legacy_frame_without_new_columns(monkeypatch):
    frame = pd.DataFrame(
        {
            "fecha": ["2026-08-05", "2026-08-06", "2026-08-07"],
            "valor_cartera": [100.0, 101.0, 99.0],
            "P/L dia": [None, 1.0, -2.0],
            "% dia": [None, 0.01, -0.019802],
            "fuente": ["Alpaca", "Alpaca", "Alpaca"],
        }
    )
    captured = []
    monkeypatch.setattr(web_app.st, "altair_chart", lambda chart, **_: captured.append(chart))

    web_app._portfolio_value_chart({}, None, days=None, equity_df=frame)

    spec = captured[0].to_dict()
    assert any(layer.get("mark", {}).get("type") == "text" for layer in spec["layer"])


def test_label_helpers_use_neutral_gray_for_missing_and_zero():
    assert web_app._portfolio_pct_label(None) == "n/d"
    assert web_app._portfolio_pct_label(0.0) == "0.00%"
    assert web_app._portfolio_pct_color(None) == "#374151"
    assert web_app._portfolio_pct_color(0.0) == "#374151"
