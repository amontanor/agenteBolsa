# P-L307 — corte Jetson 0.4.307 (P-L147 + P-L149) — `deployed`

Dictamen: `deployed`. Ejecutado 18-sep-2026 ~23:20Z (19-sep 01:20 CEST),
XNYS cerrado, postmarket sesión terminal `completed` (20:23Z),
sin leases activos.

## Contenido portado (splice `FROM agente-bolsa:0.4.306-arm64`)

- **P-L147**: `crew.py` de Jetson es la variante P-L110 v2 (distinta de
  Windows) → NO se copia: parche por ancla de solo 2 hunks (import +
  `additional_params={"extra_headers": ...}`), `py_compile` OK.
- **P-L149**: `trade_decision.py` de Jetson diverge de Windows
  (`capital_ladder`, `challenger_policy`), 138 líneas de diferencia →
  parche por anclas de 9 hunks (`_toxic_veto_reason`,
  `_sin_patron_quota_order`, veto con exención, quota, selection_report,
  metadatos), `py_compile` OK.
- `config.py` de Jetson vs Windows: solo el hunk P-L149 → copia directa.
- `__init__.py` → `0.4.307`.
- Incidente propio: primer `cp` copió el `config.py` viejo (fallback);
  detectado por verificación en contenedor (`no attribute
  toxic_score_cap`), corregido y reconstruido `--no-cache`.

## Imagen y verificación

- Imagen `sha256:0f3d6baaa656ad60e5` (0.4.307-arm64), labels
  `0.4.307 / port-p147-p149-0.4.307`.
- Contenedor efímero: version `0.4.307`, `crew_headers`, `veto`,
  `quota`, `caps 18.0 0.2 1 True`.

## Corte y salud

- Preflight `diagnose` ok; escritores detenidos por `compose stop`
  canónico (`WRITERS_STOPPED`).
- Snapshot frío `cold-pre-0.4.307-20260918T2320Z` ok (UUID nvme
  verificado).
- Selector → `0.4.307-arm64` (backup `runtime.env.bak-p147`).
- `deploy-agente-bolsa`: **verde a la primera** (sin timeout).
- Doble salud: HTTP `/ /health /_stcore/health /kindle` = 200/200/200/200;
  3 contenedores healthy restarts=0 oom=false; version `0.4.307`;
  lock owner_alive/token_match; kernel True sin violaciones; PAPER/
  live-off/auto-off; 0 ómnibus recientes, 0 `database is locked`,
  0 errores en logs (+75 s segunda lectura idéntica).

## Residual

- `auxiliary` ahora `healthy` (el latch `ci_digest` de las 06:30Z quedó
  atrás tras el recreo).
- 103 `MissingSessionID` de la sesión 18-sep son pre-corte (P-L147 llega
  en este despliegue): verificar en la próxima sesión que crews
  autentican y las compras dejan de ser `Fallback determinista`.
