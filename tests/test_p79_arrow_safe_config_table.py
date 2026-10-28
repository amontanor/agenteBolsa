import inspect
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from agente_bolsa import web_app

MIXED_CONFIG_ROWS = [
    {"clave": "feature_enabled", "valor": True},
    {"clave": "max_orders", "valor": 4},
    {"clave": "risk_fraction", "valor": 0.125},
    {"clave": "endpoint", "valor": "https://example.invalid/v1"},
    {"clave": "database", "valor": Path("data/state/agente_bolsa.sqlite3")},
    {"clave": "watchlist", "valor": ("AAPL", "MSFT")},
    {"clave": "missing_value", "valor": None},
]


def test_base_config_rows_reproduce_arrow_type_error():
    frame = pd.DataFrame(MIXED_CONFIG_ROWS)

    with pytest.raises(pa.ArrowException):
        pa.Table.from_pandas(frame, preserve_index=False)


def test_config_display_frame_is_arrow_safe_and_homogeneous():
    frame = web_app._config_display_dataframe(MIXED_CONFIG_ROWS)

    assert list(frame.columns) == ["clave", "valor"]
    assert frame["valor"].map(type).eq(str).all()
    pa.Table.from_pandas(frame, preserve_index=False)
    assert frame["valor"].tolist() == [
        "true",
        "4",
        "0.125",
        "https://example.invalid/v1",
        str(Path("data/state/agente_bolsa.sqlite3")),
        "AAPL, MSFT",
        "n/d",
    ]


def test_config_display_frame_preserves_rows_without_mutating_inputs():
    rows = [dict(row) for row in MIXED_CONFIG_ROWS]
    before = [dict(row) for row in rows]

    frame = web_app._config_display_dataframe(rows)

    assert rows == before
    assert frame["clave"].tolist() == [row["clave"] for row in rows]
    assert frame.index.tolist() == list(range(len(rows)))


def test_page_config_uses_the_normalized_display_boundary():
    source = inspect.getsource(web_app.page_config)

    assert "_config_display_dataframe(rows)" in source
    assert "pd.DataFrame(rows)" not in source


def test_config_display_frame_keeps_zero_distinct_from_missing():
    frame = web_app._config_display_dataframe(
        [
            {"clave": "zero_int", "valor": 0},
            {"clave": "zero_float", "valor": 0.0},
            {"clave": "missing", "valor": None},
        ]
    )

    assert frame["valor"].tolist() == ["0", "0.0", "n/d"]
