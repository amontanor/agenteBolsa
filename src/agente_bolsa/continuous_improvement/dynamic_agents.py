"""Fabrica de agentes especialistas definidos como datos (T2.2).

El comite puede crear agentes especialistas nuevos (p. ej. "vigilante de short
squeeze") sin tocar codigo Python: una fila en `agent_definitions` describe rol,
goal, prompt, inputs y output_schema. `DynamicSpecialistAgent` se instancia desde
esa fila, construye su prompt desde `prompt_store` y valida su salida contra el
schema. Un gate determinista limita el numero y exige que la salida declare
`confidence` y `evidence`. Cada cierto numero de sesiones se puntua su utilidad y
se retiran los inutiles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


# Catalogo de inputs permitidos (reports/tablas que un agente puede recibir).
ALLOWED_INPUT_CATALOG: frozenset[str] = frozenset(
    {
        "latest_closed_market_technical_study",
        "latest_signal_learning",
        "latest_daily_learning_digest",
        "latest_post_market_learning",
        "latest_research_evidence",
        "market_thesis",
        "performance_daily",
        "signal_outcomes",
        "distilled_lessons",
        "market_state",
    }
)

REQUIRED_OUTPUT_KEYS: frozenset[str] = frozenset({"confidence", "evidence"})

# Score minimo de utilidad para sobrevivir a la evaluacion periodica.
DEFAULT_MIN_UTILITY_SCORE = 0.45


def validate_agent_definition(
    definition: dict[str, Any],
    *,
    existing_active: int,
    max_agents: int,
) -> tuple[bool, str]:
    """Gate determinista para crear un agente dinamico."""

    if not str(definition.get("agent_key") or "").strip():
        return False, "falta agent_key"
    if not str(definition.get("role") or "").strip():
        return False, "falta role"
    if existing_active >= max_agents:
        return False, f"cupo de agentes dinamicos agotado ({existing_active}/{max_agents})"
    inputs = definition.get("inputs") or []
    if not isinstance(inputs, list):
        return False, "inputs debe ser una lista"
    bad_inputs = [item for item in inputs if item not in ALLOWED_INPUT_CATALOG]
    if bad_inputs:
        return False, f"inputs fuera del catalogo permitido: {bad_inputs}"
    schema = definition.get("output_schema") or {}
    schema_keys = set(schema.keys()) if isinstance(schema, dict) else set()
    missing = REQUIRED_OUTPUT_KEYS - schema_keys
    if missing:
        return False, f"output_schema debe declarar {sorted(missing)}"
    return True, "ok"


def create_agent(
    store: Store,
    settings: Settings,
    definition: dict[str, Any],
    *,
    created_by: str = "DecisionCommitteeAgent",
) -> dict[str, Any]:
    """Valida y registra un agente dinamico (CREATE_AGENT)."""

    max_agents = int(getattr(settings, "max_dynamic_agents", 8))
    existing_active = len(store.agent_definitions(status="ACTIVE"))
    ok, reason = validate_agent_definition(definition, existing_active=existing_active, max_agents=max_agents)
    if not ok:
        return {"ok": False, "error": reason}
    item = {
        "agent_key": definition["agent_key"],
        "role": definition.get("role", ""),
        "goal": definition.get("goal", ""),
        "prompt_key": definition.get("prompt_key"),
        "inputs": definition.get("inputs", []),
        "output_schema": definition.get("output_schema", {}),
        "status": "ACTIVE",
        "created_by": created_by,
        "performance": {},
    }
    store.upsert_agent_definition(item)
    return {"ok": True, "agent_key": item["agent_key"]}


class DynamicSpecialistAgent:
    """Agente especialista instanciado desde una fila de agent_definitions."""

    def __init__(self, definition: dict[str, Any]) -> None:
        self.definition = definition
        self.agent_key = str(definition.get("agent_key"))
        self.role = str(definition.get("role", ""))
        self.goal = str(definition.get("goal", ""))
        self.prompt_key = definition.get("prompt_key")
        self.inputs = list(definition.get("inputs") or [])
        self.output_schema = dict(definition.get("output_schema") or {})

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DynamicSpecialistAgent:
        return cls(row)

    def build_messages(self, settings: Settings, context: dict[str, Any]) -> list[dict[str, str]]:
        import json

        from ..prompt_store import get_prompt

        default_prompt = (
            f"Eres {self.role}. Objetivo: {self.goal}. Responde SOLO JSON con las claves "
            f"{sorted(self.output_schema.keys())}, incluyendo confidence (0-1) y evidence (lista)."
        )
        system = get_prompt(settings, str(self.prompt_key), default_prompt) if self.prompt_key else default_prompt
        declared = {key: context.get(key) for key in self.inputs}
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(declared, ensure_ascii=True, default=str)},
        ]

    def validate_output(self, output: Any) -> tuple[bool, str]:
        if not isinstance(output, dict):
            return False, "la salida no es un objeto JSON"
        missing = [key for key in self.output_schema.keys() if key not in output]
        if missing:
            return False, f"faltan claves del schema: {missing}"
        for key in REQUIRED_OUTPUT_KEYS:
            if key not in output:
                return False, f"falta clave obligatoria {key}"
        confidence = output.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            return False, "confidence debe ser un numero en [0,1]"
        if not isinstance(output.get("evidence"), (list, tuple)):
            return False, "evidence debe ser una lista"
        return True, "ok"


def instantiate_active(store: Store) -> list[DynamicSpecialistAgent]:
    return [DynamicSpecialistAgent.from_row(row) for row in store.agent_definitions(status="ACTIVE")]


def _utility_score(performance: dict[str, Any]) -> float:
    """Score de utilidad [0,1]: ¿sus llamadas correlacionan con outcomes?"""

    correct = float(performance.get("correct_calls") or 0)
    total = float(performance.get("total_calls") or 0)
    if total <= 0:
        return 0.5  # sin datos: neutral, no se retira aun
    return round(correct / total, 4)


def score_dynamic_agents(
    store: Store,
    *,
    min_score: float = DEFAULT_MIN_UTILITY_SCORE,
    min_calls: int = 10,
) -> list[dict[str, Any]]:
    """Puntua cada agente dinamico ACTIVE y retira los inutiles."""

    results: list[dict[str, Any]] = []
    for row in store.agent_definitions(status="ACTIVE"):
        performance = row.get("performance") or {}
        score = _utility_score(performance)
        total = float(performance.get("total_calls") or 0)
        retired = False
        if total >= min_calls and score < min_score:
            store.set_agent_status(row["agent_key"], "RETIRED", performance={**performance, "last_score": score})
            retired = True
        results.append(
            {
                "agent_key": row["agent_key"],
                "score": score,
                "total_calls": total,
                "retired": retired,
            }
        )
    return results
