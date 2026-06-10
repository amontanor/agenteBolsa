"""Contexto del repositorio para el ProgrammerAgent (T1.4).

Arma un prompt compacto con: el arbol de `src/agente_bolsa/` (solo nombres), la
interfaz `Strategy`, la estrategia builtin como ejemplo, un test de ejemplo y las
reglas de Definition of Done (seccion 0.2). Se acota por tokens para no desbordar
el contexto del modelo.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .context_compaction import truncate_string

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings


DOD_RULES = """\
Definition of Done (resumen seccion 0.2):
1. `python -m pytest tests/ -x -q` pasa completo.
2. `ruff check src tests` sin errores.
3. El cambio incluye SIEMPRE un archivo de test nuevo que cubre camino feliz y de error.
4. Mensajes/log en espanol; identificadores en ingles.
5. No tocar kernel.py, broker.py, execution.py, risk.py, config.py ni .env.
6. Una estrategia nueva vive en src/agente_bolsa/strategies/<nombre>.py y expone get_strategy().
"""

OUTPUT_CONTRACT = """\
Contrato de salida ESTRICTO. Devuelve UN unico objeto JSON valido, sin markdown:
{
  "file_edits": [{"path": "src/agente_bolsa/strategies/<nombre>.py", "content": "<contenido COMPLETO>"},
                 {"path": "tests/test_<nombre>.py", "content": "<contenido COMPLETO del test>"}],
  "test_commands": ["python -m pytest tests/test_<nombre>.py -q"],
  "strategy_name": "<nombre>",
  "strategy_version": "1",
  "rationale": "<por que esta estrategia>",
  "expected_metric_impact": "<impacto esperado en hit rate/expectancy>"
}
- `content` debe ser el archivo COMPLETO, nunca un diff parcial.
- DEBES incluir SIEMPRE un archivo de test nuevo bajo tests/.
- La estrategia debe heredar de Strategy e implementar generate_candidates.
"""


def _module_tree(root: Path, *, max_entries: int = 200) -> str:
    if not root.exists():
        return "(arbol no disponible)"
    names: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            rel = path.relative_to(root.parent).as_posix()
        except ValueError:
            rel = path.name
        names.append(rel)
        if len(names) >= max_entries:
            names.append("... (truncado)")
            break
    return "\n".join(names)


def _read(path: Path, *, limit: int) -> str:
    try:
        return truncate_string(path.read_text(encoding="utf-8"), limit)
    except OSError:
        return "(no disponible)"


def build_repo_context(
    settings: "Settings",
    targets: list[str] | None = None,
    *,
    char_budget: int = 16000,
) -> str:
    """Construye el bloque de contexto para el prompt del ProgrammerAgent."""

    root = Path(getattr(settings, "improvement_workspace_dir", Path("."))) / "src" / "agente_bolsa"
    strategies_dir = root / "strategies"
    tree = _module_tree(root)
    base_iface = _read(strategies_dir / "base.py", limit=4000)
    example_strategy = _read(strategies_dir / "builtin_breakout.py", limit=4000)
    example_test = _read(
        Path(getattr(settings, "improvement_workspace_dir", Path("."))) / "tests" / "test_strategy_registry.py",
        limit=4000,
    )

    parts = [
        "== ARBOL src/agente_bolsa (solo nombres) ==",
        tree,
        "\n== INTERFAZ Strategy (strategies/base.py) ==",
        base_iface,
        "\n== EJEMPLO de estrategia (strategies/builtin_breakout.py) ==",
        example_strategy,
        "\n== EJEMPLO de test ==",
        example_test,
        "\n== REGLAS ==",
        DOD_RULES,
        "\n== CONTRATO DE SALIDA ==",
        OUTPUT_CONTRACT,
    ]
    if targets:
        parts.insert(0, f"== OBJETIVOS == {', '.join(targets)}\n")
    return truncate_string("\n".join(parts), char_budget)
