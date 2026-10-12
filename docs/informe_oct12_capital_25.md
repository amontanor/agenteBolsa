# Capital hasta 25% — candidato .368, 12 de octubre de 2026

Dictamen: candidato local preparado; no desplegado ni activado. El mercado está
abierto y la aceptación N3 completa sigue pendiente. La preparación de código
no acredita cinco sesiones shadow, mejora económica ni protección broker.

## Implementación y autoridad

- Tamaño: etapas versionadas 15%/20%/25%, tope ordinario 2,5% del equity,
  tres/cuatro/cuatro compras. El clamp se aplica al importe ya ajustado por
  stop y multiplicadores, sin duplicar el factor 0,5. Cash y buying power se
  intersectan; se reservan BUY broker, planes locales y planes del ciclo.
  El enlace aún no reconciliado se cuenta conservadoramente por ambos lados.
- Ausencia de política: shadow, aprendizaje existente y estrategias actuales.
  Una activación inválida bloquea BUY, incluidas las preconstruidas, y conserva
  la evaluación de SELL con el cupo global legacy. No se eleva ese cupo de EXIT.
- Stop/riesgo desconocido: bloquea nuevas BUY con la política activa.
- Multiplicador cero: tamaño cero. Es una corrección intencional del defecto
  previo `or 1`; constituye la única excepción deliberada a la paridad de
  tamaños positivos con política nueva desactivada.
- Observación: evento append-only independiente `capital_allocation_shadow`,
  hash e ID por política/ciclo, IDs exactos y frontera de rechazo. Reutiliza el
  contexto de riesgo ya consultado: ninguna consulta adicional para observarlo.
  Cada etapa acumula sus reservas proyectadas; son presupuestos hipotéticos,
  no oportunidades ejecutables ni beneficios. Campos ausentes: unavailable.
- Score: challenger 55/20/15/10 y calibración del score actual separados; noticias
  disponibles al decidir, deduplicación, identidad del modelo/prompt y recibos
  maduros. Datos ausentes no redistribuyen pesos. Confianza declarada no es
  probabilidad de beneficio. No hay consultas nuevas, cambios de selección,
  aprendizaje real ni autoridad sobre órdenes.
- Ampliaciones: evaluador puro cubre nueva señal, sesión XNYS completa,
  ganancia, tesis, órdenes y protección exacta por cantidad/parent/OCO. La ruta
  actual no demuestra la protección canónica de la cantidad añadida: incluso
  con enable_adds=true, rechaza `controlled_add_protection_unavailable`.
  No se cancela ni modifica protección existente. El sublote requiere diseñar,
  probar y revisar el diff concreto del adaptador broker antes de habilitarlo.
- Tope superior 5%: helper exige evidencia independiente, score>=85,
  componentes completos, expectativa neta positiva, costes y aprobación; la
  ruta actual no consume un shadow score como autoridad. Promoción independiente
  y adaptador validado pendientes; actualmente no habilita ese tamaño.

## Activación y evidencia

Archivo previsto: DATA_DIR/config/capital_allocation_policy.json. Su ausencia
es el estado seguro; este lote no crea ni modifica configuración productiva.
`mode=guarded_active` exige paper/live/auto-apply y límites vigentes correctos,
registro y árbol base congelados, hash de política, aprobación exacta y recibos
canónicos `capital_allocation_session_reviewed` y
`capital_allocation_evidence_reviewed`, resueltos mediante lectura acotada.
Un JSON con conteos sin los eventos exactos no activa la política.

Primer gate: cinco sesiones XNYS completas posteriores al registro y a su
cobertura efectiva, identidad>=95%, cero incidentes críticos y reconciliación
de cantidades/protección. Se conservan requisitos adicionales del ladder.
20% exige 35 compras maduras/25 controles; 25%, 50/35, con dos ventanas no
solapadas positivas después de costes y deterioro máximo de drawdown de 1pp.
El CLI `python -m agente_bolsa.tools.capital_allocation_status --data-dir RUTA
--json` es de solo lectura: no transforma fechas observadas en sesiones completas,
no aprueba ni promociona. Está acotado y expone saturación/errores/conflictos.

## QA y procedencia

Base exacta HEAD 63cb6f9883f22c0d11dba20dd59c315ceae5dc0e,
tree a7167bca1b9387c40eb37d32d3497505dd573bf7. Módulos entregados desde ramas
score 5d30e8f67e6f384a4ae3b3b5ec5a9aebc2e7cafe y adds
d7f3a124ece0ee3e1ed9fc36f4973594674e1eb0; integración explícita de sus seis
archivos, sin portar otras ramas. Ningún archivo protegido modificado:
objetos Git de kernel/config/broker/execution/risk iguales a la base.

Batería focal combinada:315 passed,0 failed (incluye la de105; no se suman).
Ruff, diff, configuración paper aislada y NUL src/tests 511/0 pasan.
Python del proyecto, PYTHONPATH exacto, DATA_DIR temporal, _env_file=None,
proveedores locales y bloqueo de red externa. Fallo inicial de fixture EXIT:
lambda de test no aceptaba nuevo keyword include_allocation; fixture corregida,
manteniendo su prueba del cupo legacy. No se clasifica como fallo de producción.

Snapshot de fuentes/tests, hashes y objetos protegidos:
EF99/release_oct12_0368_focal_snapshot.json. Suite completa aún no ejecutada:
una por árbol funcional definitivo, después del cierre y preflight. También
pendientes smoke/configuración/kernel completos y QA ARM sin volúmenes vivos.
No se certifica N3 ni se ha construido una imagen .368 de producción.

## Secuencia pendiente

1. Revalidar quietud al cierre: XNYS cerrado, postmarket terminal, sin jobs,
   reintentos, leases, reconciliaciones ni validaciones/despliegues activos.
   Si falla: precondition_not_met; no fabricar quietud.
2. Fullsuite única del árbol congelado, smoke offline, QA ARM y manifiesto exacto.
   Los fallos se investigan con evidencia; no repetir un árbol sin causa.
3. Desplegar inicialmente observación, conservando .364 y .321 para rollback,
   mediante runbook. Confirmar imagen/hashes, doble salud>=75s y OOM/recursos600s.
   No activar tamaños ni adds ni score por el mero despliegue del observador.
4. Obtener cinco sesiones completas y recibos revisados. Activar tamaños como
   lote separado solo entonces. Ampliaciones y scoring conservan gates propios.
5. Comparación cronológica principal cinco sesiones, secundarias tres/diez,
   costes/spread/slippage/rotación/gaps, control y SPY con flujos equivalentes.
   No existe aún un resultado económico atribuible a .368.


## Identidad del checkpoint y continuidad

HEAD funcional579dc2ad173454aa632cf26420e30742251a1c2d,
tree612df176c1adc580293ed4e48172681826c9bec4, worktree limpio al commit.
Reanudación de QA/corte de observación a las22:45Madrid del12-oct mediante
automatización validar-mejoras-bolsa-tras-cierre actualizada (ACTIVE), pausándose
al terminar el intento. No activa política, tamaños, adds ni score. Cualquier
precondición ausente detiene el intento sin fabricar quietud. No cambia la
revisión del12. Recibo EF99/release_oct12_0368_checkpoint.json.
