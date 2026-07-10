from scripts.check_no_nulls import _iter_targets, main


def test_explicit_targets_include_active_text_formats(tmp_path):
    markdown = tmp_path / "plan.md"
    config = tmp_path / "config.json"
    markdown.write_text("ok\n", encoding="utf-8")
    config.write_text('{"ok": true}\n', encoding="utf-8")

    assert _iter_targets([str(markdown), str(config)]) == [markdown, config]
    assert main([str(markdown), str(config)]) == 0


def test_null_markdown_and_invalid_json_are_rejected(tmp_path):
    markdown = tmp_path / "plan.md"
    config = tmp_path / "config.json"
    markdown.write_bytes(b"plan\x00roto")
    config.write_text("{no-json}\n", encoding="utf-8")

    assert main([str(markdown), str(config)]) == 1
