"""P-L171: el semaforo del panel debe usar las rutas reales de Settings.

La pagina llamaba ``build_status()`` sin argumentos, asi que tomaba
``/app/data/state/...`` y en el contenedor dictaminaba DOWN por base
inexistente mientras el stack estaba sano.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from agente_bolsa.tools.system_status import DOWN, build_status
from agente_bolsa.web_app import _system_status_paths


def _settings(tmp_path: Path) -> SimpleNamespace:
    data_dir = tmp_path / "data"
    (data_dir / "state").mkdir(parents=True)
    return SimpleNamespace(
        data_dir=data_dir,
        database_path=data_dir / "state" / "agente_bolsa.sqlite3",
    )


def test_status_paths_follow_settings_not_module_defaults(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    db_path, reports_dir = _system_status_paths(settings)

    assert db_path == settings.database_path
    assert reports_dir == settings.data_dir / "reports"
    assert "/app/data" not in str(db_path)


def test_missing_database_is_reported_with_the_given_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    status = build_status(
        db_path=settings.database_path,
        reports_dir=settings.data_dir / "reports",
    )

    assert status["verdict"] == DOWN
    assert "Base de datos" == status["components"][0]["name"]
    assert str(settings.database_path) in status["components"][0]["detail"]


def test_existing_database_is_not_down_for_missing_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path):
        pass

    status = build_status(
        db_path=settings.database_path,
        reports_dir=settings.data_dir / "reports",
    )

    components = {item["name"]: item for item in status["components"]}
    assert components["Base de datos"]["state"] != DOWN
