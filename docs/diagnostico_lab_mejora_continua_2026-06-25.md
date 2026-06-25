# Diagnóstico: por qué el lab de mejora continua aplica 0 cambios (25-jun-2026)

Pregunta del plan (sección 2): "Laboratorio: 0 cambios de código aplicados, 1.203
validaciones PENDING, 0 reglas activas… la mejora continua no mejora nada."

## Conclusión: NO está roto — es correctamente conservador

Para que el lab APLIQUE un cambio se exigen **dos puertas** (en
`continuous_improvement/experiments.py:407` y `:803-816`):

1. **`ALLOW_AUTO_APPLY_IMPROVEMENTS=true`.** Hoy está en **false** — por diseño y
   seguridad: el sistema NO se auto-modifica el código sin supervisión humana. Esto
   es un principio del propio plan ("autonomía baja en ejecución real / código").
2. **La validación debe estar en `READY_TO_APPLY`.** Pero los validadores
   (`agents.py:1893,1952,1998,2035…`) sólo marcan `READY_TO_APPLY` si, además de
   pasar, hay **evidencia suficiente**: p.ej. entry_quality exige ≥5 señales de
   calibración o backtest; consolidación ≥3 duplicados; pre-earnings ≥2 grandes
   ganadores bloqueados con FP≤20%. Si no hay esa muestra madura, un PASSED se
   **degrada a PENDING** (`agents.py:1664-1736`).

Con poco histórico de trades ejecutados (llevamos ~0 ejecuciones reales y ~7 semanas
de señales), **casi nada llega a READY_TO_APPLY** → se queda PENDING. Y aunque
llegara, la puerta 1 (auto-apply off) impide aplicarlo solo.

## Implicación (cómo se obtiene valor del lab)

El lab es un **motor de propuestas que espera curación humana**, no un aplicador
autónomo. Las palancas reales son:

1. **Revisar periódicamente las propuestas `READY_TO_APPLY`** (las que SÍ tienen
   evidencia) y aplicar a mano las buenas, desde el panel ("Learning Lab" /
   "Code Changes") o vía API. Comando para verlas:
   `\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement --json`
   → campos `ready_initiatives`, `applied_changes`, `allow_auto_apply`.
2. **Generar más datos maduros** para que más validaciones alcancen READY_TO_APPLY.
   El fix de `material_risk` (v0.4.45) va en esa dirección: si por fin entran trades
   paper, el lab tendrá outcomes ejecutados que validar.
3. **(Opcional, con criterio) Auto-apply acotado:** activar `ALLOW_AUTO_APPLY_IMPROVEMENTS`
   SOLO para una clase de cambios de bajo riesgo y reversibles (p.ej. ajustes de
   umbral en `adaptive_config.json`, que ya es la única auto-modificación que hoy
   funciona end-to-end). NO para cambios de código. Requiere decisión humana y, idealmente,
   rollback automático (champion/challenger ya existe en `experiments.py`).

## Veredicto
"La mejora continua no mejora nada" = en realidad **"la mejora continua no aplica
nada sin evidencia ni aprobación humana"**, que es el comportamiento correcto y
seguro. El trabajo no es "arreglar el lab", es (a) alimentarlo con datos de trades
reales (desbloquear la operativa) y (b) montar una rutina de revisión humana de sus
propuestas READY_TO_APPLY. Ambas dependen de que el sistema **opere** — que es
justo lo que estamos desatascando con el embudo (B2) y el fix de material_risk.
