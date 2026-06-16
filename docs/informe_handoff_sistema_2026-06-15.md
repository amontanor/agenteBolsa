# Informe de handoff del sistema

Fecha: 2026-06-15
Proyecto: `agenteBolsa`
Rama actual observada: `codex/mejora_continua`

## 1. Resumen ejecutivo

Este proyecto es un sistema de trading asistido por agentes, centrado en acciones USA, con una arquitectura que combina:

- filtros deterministas y reglas de riesgo duras,
- análisis técnico y de contexto,
- uso controlado de LLMs para priorización y mejora continua,
- aprendizaje persistente sobre señales, decisiones y resultados,
- laboratorio autónomo para proponer cambios en estrategias, prompts, reglas y código.

El objetivo no es "hacer trading con un LLM", sino construir un grupo de agentes que:

- estudie el mercado,
- detecte oportunidades,
- aprenda de errores y aciertos,
- genere hipótesis falsables,
- pruebe mejoras en sandbox,
- y solo promueva cambios cuando hay evidencia suficiente.

La filosofía actual del sistema es:

- autonomía alta en investigación, aprendizaje, paper trading y mejora continua,
- autonomía baja en ejecución real, credenciales, broker, sizing crítico y live trading.

## 2. Qué hace hoy el sistema

### Operativa de mercado

El sistema genera candidatos técnicos, los clasifica por setup, score, momentum, volumen, contexto técnico y memoria histórica reciente. Después:

- filtra entradas con reglas deterministas,
- incorpora noticias/sentimiento,
- consulta al comité de decisión LLM,
- construye planes de compra,
- y vuelve a pasar por riesgo antes de aceptar una orden.

En paper trading puede operar automáticamente si todo el pipeline está sano. En live trading sigue bloqueado por diseño salvo gates explícitos.

### Aprendizaje

El sistema guarda y reevalúa:

- outcomes de señales,
- memoria por setup,
- memoria por símbolo/setup,
- falsos positivos y falsos negativos,
- reglas `shadow` y `active`,
- lecciones destiladas,
- revisiones post-mercado,
- y reportes diarios de aprendizaje.

No aprende como un único modelo entrenado. Aprende mediante:

- agregados estadísticos,
- priorización por evidencia reciente,
- reglas shadow,
- walk-forward,
- retrospectiva,
- y promoción/retiro de lecciones.

### Mejora continua

Existe un laboratorio multiagente residente que:

- detecta problemas y oportunidades internas,
- crea iniciativas, tareas, hipótesis y propuestas,
- valida cambios,
- puede aplicar cambios de código en sandbox git,
- guarda artefactos y rollback,
- y monitoriza si los cambios aplicados mejoran o degradan el sistema.

## 3. Objetivo esperado por el usuario

La intención del usuario, consolidada en esta rama, es evolucionar el proyecto hacia un grupo de agentes autónomos expertos que:

1. investiguen por internet y con proveedores externos,
2. no acepten narrativas sin evidencia y trazabilidad,
3. aprendan de resultados reales y no solo de ideas,
4. puedan crear, modificar o retirar agentes, reglas y estrategias,
5. puedan proponer y aplicar cambios de código de forma segura,
6. usen champion/challenger y shadow antes de promover cambios relevantes,
7. y mejoren solos sin poner en riesgo el núcleo operativo.

En términos prácticos, el usuario quiere un sistema que se comporte más como un equipo buy-side disciplinado que como un bot reactivo:

- investiga,
- documenta,
- contrasta,
- prueba,
- aprende,
- y solo entonces cambia.

## 4. Objetivo esperado por el sistema

Si se interpreta el diseño actual, el objetivo interno del sistema es:

- maximizar decisiones con edge repetible,
- minimizar sobreajuste,
- bloquear operativa cuando faltan datos críticos,
- conservar trazabilidad completa,
- y aumentar autonomía solo cuando el historial lo justifica.

Las métricas implícitas más importantes son:

- alpha frente a SPY,
- Sharpe,
- hit rate,
- profit factor,
- max drawdown,
- falsos positivos y falsos negativos,
- estabilidad por régimen,
- capacidad de promoción sin rollback posterior.

## 5. Arquitectura actual por capas

### Capa 1. Núcleo operativo

Responsable de:

- configuración,
- riesgo,
- broker,
- ejecución,
- scheduler,
- decisiones de compra/venta,
- persistencia SQLite.

Aquí están los límites más sensibles. El sistema ya protege especialmente:

- `.env`,
- `broker.py`,
- `execution.py`,
- `risk.py`,
- `config.py`,
- partes del flujo de decisión.

### Capa 2. Investigación y contexto

Incluye:

- análisis técnico,
- noticias y sentimiento,
- contexto macro,
- tesis de mercado,
- reportes de calidad de datos,
- y desde esta última iteración, una capa persistente de evidencia externa.

Esa capa de evidencia guarda:

- `evidence_id`,
- símbolo o scope,
- tipo de fuente,
- proveedor,
- URL,
- fecha publicada,
- fecha de consulta,
- fiabilidad,
- frescura,
- estado de calidad,
- payload original.

### Capa 3. Aprendizaje

Incluye:

- `signal_outcomes`,
- `learning_observations`,
- `learning_daily_summaries`,
- `learning_policy_candidates`,
- `strategy_rules`,
- `distilled_lessons`,
- `operational_learning`,
- `post_market_review`.

Es la capa que transforma resultados en memoria reusable.

### Capa 4. Laboratorio autónomo

Incluye:

- eventos,
- tareas,
- hipótesis,
- propuestas,
- validaciones,
- iniciativas,
- applied changes,
- sandbox git,
- watchdog de cambios,
- agentes dinámicos,
- promoción de autonomía.

Es la capa que permite que el sistema se mejore a sí mismo con controles.

### Capa 5. Dashboard y observabilidad

El dashboard Streamlit ya expone:

- estado operativo,
- cartera,
- decisiones,
- aprendizaje,
- mejora continua,
- autonomía,
- y ahora también:
  - `Research Inbox`,
  - `Learning Lab`,
  - `Code Changes`,
  - `Strategy Lab`,
  - `Agent Roster`.

## 6. Agentes y roles

Hay dos familias principales de agentes.

### Agentes estáticos

Definidos en `config/agents.yaml`, cubren:

- control,
- research,
- validation,
- execution,
- learning.

Entre ellos:

- `orchestrator`
- `macro_news_researcher`
- `technical_analyst`
- `fundamental_analyst`
- `hypothesis_generator`
- `quant_backtester`
- `risk_manager`
- `decision_committee`
- `post_market_review_agent`
- `self_improvement_engineer`

### Agentes añadidos/reforzados en esta fase

Se han formalizado o añadido:

- `web_research_agent`
- `source_reliability_agent`
- `fundamental_filings_agent`
- `macro_calendar_agent`
- `lesson_curator_agent`

Además existe soporte para agentes dinámicos en base de datos, con catálogo de inputs permitido y retirada automática si su utilidad es baja.

## 7. Qué se ha implementado recientemente

### Evidencia externa de investigación

Se añadió una tabla `research_evidence` y un módulo dedicado para:

- persistir evidencia macro y por símbolo,
- puntuar fiabilidad,
- medir frescura,
- dejar reporte `latest_research_evidence.json`,
- y bloquear compras cuando falte evidencia crítica si el modo fail-closed está activo.

### Integración en decisión

`trade_decision.py` ahora:

- construye contexto de investigación,
- lo pasa al prompt del comité,
- pide referenciar `evidence_ids` en la razón,
- y añade un `research_guard` antes de aceptar compras.

### Curación de lecciones

Se creó un `lesson_curator` que reutiliza el destilador existente para:

- destilar,
- promover,
- revalidar,
- debilitar,
- y retirar lecciones.

También quedó conectado al runtime del laboratorio para que forme parte del ciclo autónomo.

### Dashboard

Se añadieron paneles de producto para que la capa de investigación, aprendizaje, agentes y cambios sea visible y auditable.

## 8. Estado actual

Estado general actual: bueno y operativo para seguir iterando.

Lo que está sólido:

- pipeline de aprendizaje ya real,
- shadow rules ya presentes,
- sandbox de código ya integrado,
- autonomía por niveles ya implementada,
- mejora continua con iniciativas/propuestas/validaciones ya funcional,
- dashboard bastante completo,
- evidencia externa ya integrada en una primera versión útil,
- bloqueo de compras si falta investigación crítica.

Lo que sigue bloqueado o controlado:

- live trading no debe activarse automáticamente,
- núcleo de broker/riesgo/ejecución sigue protegido,
- cambios críticos no deben promoverse sin gates más fuertes.

## 9. Qué falta para llegar al objetivo completo

### Falta importante

1. Conectar más fuentes externas fiables además de las actuales.
2. Hacer que la evidencia externa alimente más capas, no solo `trade_decision`.
3. Implementar promoción champion/challenger end-to-end más automática.
4. Hacer que las estrategias nuevas nacidas del laboratorio entren de forma automática en `SHADOW` con reporting completo.
5. Añadir reporting semanal claro de:
   - qué cambió,
   - qué mejoró,
   - qué empeoró,
   - qué fue revertido.
6. Profundizar en agentes dinámicos verdaderamente útiles, no solo soportados.
7. Conectar mejor la fábrica de hipótesis con construcción automática de estrategias y su validación posterior.

### Falta para la visión "aprenden y mejoran solos"

El sistema todavía no está al final de esa visión. Está más cerca de:

- un laboratorio autónomo con buena disciplina,
- que de un equipo completamente autosuficiente que ya cierra el ciclo completo de idea -> código -> shadow -> promoción -> operación.

La base ya existe. Lo que queda es densificar el embudo y automatizar mejor la promoción basada en evidencia.

## 10. Riesgos principales

1. Sobreajuste disfrazado de aprendizaje si se promocionan reglas con poca muestra.
2. Exceso de dependencia en fuentes informales si no se endurece más el scoring de fiabilidad.
3. Saturación del laboratorio con propuestas medianas sin impacto real.
4. Agentes dinámicos creados pero sin medición de utilidad suficientemente rica.
5. Mezclar contexto narrativo de investigación con edge estadístico sin un criterio claro de peso relativo.

## 11. Recomendación para el siguiente hilo

Si se continúa en otro hilo con acceso al código, el siguiente trabajo debería ir en este orden:

1. Consolidar la capa de investigación externa:
   endurecer fiabilidad, frescura, proveedores y trazabilidad.
2. Enlazar hipótesis -> estrategia -> sandbox -> shadow -> promoción:
   cerrar el ciclo completo sin intervención manual para paper.
3. Mejorar champion/challenger:
   ventanas, métricas de promoción, rechazo y rollback.
4. Hacer más útil el roster de agentes:
   rendimiento, coste, contribución real y retiro automático.
5. Añadir un informe semanal automático de mejora del sistema:
   cambios aplicados, cambios revertidos, impacto en edge y aprendizaje nuevo.

## 12. Archivos clave para orientarse rápido

Arquitectura y persistencia:

- `src/agente_bolsa/storage.py`
- `src/agente_bolsa/config.py`
- `src/agente_bolsa/config/agents.yaml`

Decisión y operativa:

- `src/agente_bolsa/tools/trade_decision.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/scheduler.py`

Aprendizaje:

- `src/agente_bolsa/tools/daily_learning.py`
- `src/agente_bolsa/tools/operational_learning.py`
- `src/agente_bolsa/tools/post_market_review.py`
- `src/agente_bolsa/continuous_improvement/lesson_distiller.py`
- `src/agente_bolsa/continuous_improvement/lesson_curator.py`

Investigación y evidencia:

- `src/agente_bolsa/tools/news_sentiment.py`
- `src/agente_bolsa/tools/macro_context.py`
- `src/agente_bolsa/tools/research_evidence.py`

Laboratorio autónomo:

- `src/agente_bolsa/continuous_improvement/runtime.py`
- `src/agente_bolsa/continuous_improvement/agents.py`
- `src/agente_bolsa/continuous_improvement/experiments.py`
- `src/agente_bolsa/continuous_improvement/sandbox.py`
- `src/agente_bolsa/continuous_improvement/dynamic_agents.py`
- `src/agente_bolsa/continuous_improvement/autonomy.py`

Dashboard:

- `src/agente_bolsa/web_app.py`

## 13. Conclusión

El sistema ya no es solo un bot de señales. Es una plataforma de decisión y mejora continua para paper trading, con intención clara de convertirse en un grupo de agentes expertos, trazables y autoevolutivos.

La expectativa del usuario es que el sistema:

- investigue mejor,
- aprenda mejor,
- cambie mejor,
- y se acerque a una autonomía útil sin comprometer el control.

La expectativa del sistema, tal como está diseñado, es evolucionar hacia más autonomía solo cuando la evidencia estadística, operacional y de sandbox indique que esa autonomía está merecida.
