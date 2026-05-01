from agente_bolsa.tools.command_catalog import available_command_catalog, command_cheatsheet


def test_catalog_includes_web_command() -> None:
    commands = available_command_catalog()

    assert any(item["command"].endswith(" agente_bolsa.main web") for item in commands)
    assert "agente_bolsa.main web" in command_cheatsheet()
