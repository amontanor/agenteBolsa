# P-L18 — Linaje de decisión y contrafactual comparable

Fecha: 2026-07-10
Versión: 0.4.141

## Resultado

- `decision_lineage` estable y versionado acompaña recomendaciones, planes y
  payloads de broker nuevos.
- Los fills previos a P-L18 se etiquetan `legacy_unverified`; no se reconstruye
  su estrategia a posteriori.
- El control primario queda restringido a candidatos del mismo ciclo que
  superaron gates y no se planificaron por cupo, máximo tres por ejecución.
- Los candidatos bloqueados, SPY y el pool por régimen quedan separados como
  diagnósticos secundarios.
- Si no existe control comparable, el scoreboard publica `unavailable`.

## Seguridad

No se modifican kernel, broker, execution, risk, `config.py` ni `.env`. Paper y
auto-apply permanecen sin cambios.
