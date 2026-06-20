---
name: buenas-practicas
description: >
  Guía de convenciones y buenas prácticas del proyecto agenteBolsa. Úsala
  siempre que vayas a añadir código, modificar configuración, crear una
  estrategia, proponer mejoras, subir versión o tocar la documentación.
  También útil para auditar cambios antes de aplicarlos o revisar si una
  propuesta sigue el proceso correcto.
---

# Buenas prácticas — agenteBolsa

## 1. Convenciones de código

**Estructura de paquete**
- Todo el código fuente vive en `src/agente_bolsa/`.
- El paquete es instalable con `pip install -e .`.

**Configuración**
- Cada parámetro nuevo va en la clase `Settings` (pydantic) de `config.py`,
  con un `alias` en MAYÚSCULAS que se lee de `.env`.
- El mismo parámetro va también en `.env.example` con comentario explicativo.
- Nunca hardcodear valores que el operador pueda querer cambiar.

**Persistencia**
- SQLite a través de `storage.py` (`Store`).
- Tablas con `CREATE TABLE IF NOT EXISTS` — idempotentes, sin migraciones
  destructivas. Toda tabla nueva sigue ese mismo patrón.

**Eventos y logging**
- Nada importante sucede sin un evento. Usar `log_system_event` de
  `logging_utils.py` y `AgentEvent` de `models.py`.
- IDs con `new_id(prefix)` de `models.py`.

**CLI**
- Todo subsistema nuevo expone comandos en `main.py` (patrón
  `subparsers.add_parser`), siempre con opción `--json`.

**Tests**
- Pytest en `tests/`, un archivo `test_<modulo>.py` por módulo nuevo.
- Los tests **no llaman a red ni a LLM**: usar fixtures y monkeypatch.
  Ver `tests/test_continuous_improvement.py` como referencia.

**Lint**
- `ruff check src tests` sin errores (configuración en `pyproject.toml`).

**Idioma**
- Mensajes de usuario y logs: **español**.
- Identificadores de código: **inglés**.

---

## 2. Definition of Done — cualquier tarea

Antes de declarar un cambio terminado, estos cuatro checks deben pasar:

1. `python -m pytest tests/ -x -q` — suite completa verde.
2. `ruff check src tests` — sin errores.
3. `python -m agente_bolsa.main status` y `validate-agent-config --json` — funcionan.
4. Smoke: `python -m agente_bolsa.main run-once --skip-crew` — termina sin traceback.

---

## 3. Archivos bloqueados (nunca tocar sin revisión humana explícita)

Estos archivos están protegidos por `AutoApplyCodeAgent.BLOCKED_PREFIXES`
y por el kernel inmutable. **Ningún agente autónomo puede modificarlos**:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`

Si un cambio necesita tocar alguno de estos, debe pasar por revisión humana,
documentarse en `plan_mejoras_y_tareas.md` y ejecutarse de forma manual.

---

## 4. Versionado

- **Fuente única**: `src/agente_bolsa/__init__.py` (`__version__`).
- `pyproject.toml` y el sidebar del panel leen la versión de ahí.
- Formato semántico `MAJOR.MINOR.PATCH`.
- Cada entrega que añade o cambia algo **sube la versión**.
- Tras aplicar cambios de código hay que **reiniciar** el scheduler y el panel;
  un proceso ya en marcha no recoge cambios en caliente.

---

## 5. Gestión de mejoras (fuente única de verdad)

`docs/plan_mejoras_y_tareas.md` es el registro vivo de todo lo terminado y
pendiente. Proceso obligatorio:

1. Añadir la mejora como fila en la sección de backlog (estado: PENDIENTE).
2. Al ejecutarla: mover la fila a la sección de entregadas con artefacto, estado
   y cómo se verificó.
3. Subir versión (punto 4) y reiniciar el sistema.
4. Si toca decisión, ejecución o gates: validar primero en SHADOW o dry-run y
   documentar el resultado antes de activarla.

**No abrir hilos sueltos ni crear otros documentos de seguimiento.**

---

## 6. Hipótesis — estructura obligatoria

Una hipótesis sin estos campos no es válida:

| Campo | Descripción |
|---|---|
| `entry` | Condición objetiva y medible |
| `exit` | Take profit, stop o time stop |
| `invalidation` | Cuándo se descarta |
| `stop_loss` | Precio de stop (por ATR u otro criterio definido) |
| `take_profit` | Precio objetivo |
| `costs` | Comisión + slippage estimados en bps |
| `min_trades` | Mínimo de operaciones para evaluar |
| `metrics` | Sharpe OOS, drawdown, profit factor, hit rate |

---

## 7. Checklist de promoción de cambios

Antes de promover cualquier regla, threshold, prompt o estrategia a producción:

- ¿Hay tests que cubren la lógica nueva?
- ¿Hay backtest reproducible con costes y slippage?
- ¿Hay walk-forward o retrospectiva sin fuga temporal?
- ¿Hay evidencia en paper trading (si afecta a decisión, riesgo o ejecución)?
- ¿El cambio no degrada trazabilidad, kill switch, gates ni validaciones de riesgo?

Ver checklist completo en `docs/promotion_checklist.md`.

**Bloqueos automáticos:**
- Muestra pequeña o concentrada en pocas sesiones → no promover.
- Mejora retorno pero empeora drawdown → no promover.
- Depende de datos no auditados → no promover.

**Orden recomendado:** shadow → guarded_active → active. Nunca saltar pasos.

---

## 8. Estrategias

- Implementar la interfaz `Strategy` de `strategies/base.py`.
- Una estrategia nueva entra en estado SHADOW; no toca `trade_decision` hasta
  que `promotion.py` la promocione por métricas.
- Los candidatos de una estrategia SHADOW van a `shadow_candidates` del informe,
  nunca a ejecución directa.
- El registro se consulta con `strategy-registry --json`.

---

## 9. Seguridad operacional

- Paper trading por defecto. Live requiere:
  `TRADING_MODE=live` **y** `ALLOW_LIVE_TRADING=true` **y** revisión humana.
- El kernel (`kernel.py`) fija límites absolutos: drawdown 20%, pérdida diaria 5%,
  exposición por posición 15%. Ningún agente puede superar estos límites.
- `risk.py` es el límite operativo ajustable; el kernel es el suelo que nunca cede.
- Verificar integridad con `kernel-status --json` tras cambios en archivos protegidos.

---

## 10. Comandos de referencia rápida

```powershell
# Verificación básica
python -m agente_bolsa.main status
python -m agente_bolsa.main validate-agent-config --json
python -m agente_bolsa.main kernel-status --json
python -m agente_bolsa.main schedule-status

# Smoke sin LLM
python -m agente_bolsa.main run-once --skip-crew

# Diagnóstico LLM
python scripts/llm_health_check.py

# Tests + lint
python -m pytest tests/ -x -q
ruff check src tests

# Logs en vivo
python -m agente_bolsa.main log --follow
```

---

## 11. Documentación activa

Solo estos documentos se mantienen. El resto es generado automáticamente o está archivado:

| Archivo | Propósito |
|---|---|
| `README.md` | Referencia principal del proyecto |
| `docs/architecture.md` | Diseño técnico del sistema |
| `docs/operating_model.md` | Modelo operativo y rutinas |
| `docs/plan_mejoras_y_tareas.md` | **Fuente única de verdad** de mejoras y backlog |
| `docs/startup_runbook.md` | Arranque y verificación operativa |
| `docs/promotion_checklist.md` | Checklist de promoción de cambios |
| `docs/estudio_semanal.md` | Metodología de revisión semanal (plantilla) |
| `docs/tutorial_arranque_diario.md` | Arranque diario paso a paso |
| `docs/versioning.md` | Reglas de versionado |
