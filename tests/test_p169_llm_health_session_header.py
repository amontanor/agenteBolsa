"""P-L169: el chequeo de salud debe mandar la cabecera de sesion de OpenCode.

El script usaba urllib sin `x-opencode-session`, asi que Go respondia
`400 MissingSessionID` y los cinco roles se marcaban en rojo aunque la ruta
real de la app (con cabecera) funcionase.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "llm_health_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("llm_health_check_p169", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_go_and_zen_get_a_session_header() -> None:
    module = _load_module()

    go = module._provider_session_header("https://opencode.ai/zen/go/v1")
    zen = module._provider_session_header("https://opencode.ai/zen/v1")

    assert go is not None and zen is not None
    assert go[0] == "x-opencode-session"
    assert zen[0] == "x-opencode-session"
    assert len(go[1]) == 36
    assert go[1] != zen[1]


def test_session_header_is_stable_within_the_day() -> None:
    module = _load_module()

    first = module._provider_session_header("https://opencode.ai/zen/go/v1")
    second = module._provider_session_header("https://opencode.ai/zen/go/v1")

    assert first == second


def test_other_providers_get_no_header() -> None:
    module = _load_module()

    assert module._provider_session_header("https://token-plan-ams.xiaomimimo.com/v1") is None
    assert module._provider_session_header("http://127.0.0.1:8080/v1") is None
    assert module._provider_session_header(None) is None
