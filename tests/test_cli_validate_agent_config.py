from __future__ import annotations

import json
import subprocess
import sys


def test_validate_agent_config_cli_json():
    result = subprocess.run(
        [sys.executable, "-m", "agente_bolsa.main", "validate-agent-config", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["summary"]["agents"] > 0
