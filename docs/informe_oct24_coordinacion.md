# Coordinación .378 de agenteBolsa — 24 de octubre de 2026

Dictamen: `blocked_qa`. El trabajo de los dos chats quedó coordinado en el
worktree `oct19-integration`; no se construyó imagen ni se desplegó.

## Qué se integró

La base funcional sigue siendo `.376`, commit
`856740a074f7e6ac314abc1cd8339a834af51a78`, tree
`2311d35f47a7ab330d9d5cf2886c08d69162a715`. Se portó selectivamente el dashboard
de `[AgenteBolsa] Carga`, que partía de `.1.7`; no se fusionó su rama antigua
`.1.13` completa. El candidato coordinado reserva `.378` y añade carga remota en
segundo plano, snapshots por cuenta/credenciales, paginación de FILL, control de
cadencias y paneles avanzados bajo demanda. El usuario pidió que la web muestre
la fecha/hora real de cada versión: `.378` incorpora recibo durable en
`DATA_DIR/deployment_receipts.jsonl` y muestra horario de Europe/Madrid y UTC
junto a la versión después de verificar la imagen y la salud.

Identidad funcional después de ordenar imports:

- HEAD `032539c56d35e256099ee9f449146cb139bcbfdf`
- tree `668f6525b27a296c6c8566a992907f04168525a6`
- versión `0.4.378`
- base del port dashboard `856740a0`; commits fuente `4aa64bcd` y `399a5b3d`
- los blobs `config.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py` y
  `tools/risk.py` coinciden con `.376`.

## Evidencia de validación

El port del dashboard pasó 113 pruebas en su worktree, AppTest 17/17, Ruff y NUL
590. En el árbol combinado pasaron 160 pruebas focales. El informe sintético
offline registró los tres fills disponibles y persistidos, cursor repetido como
cobertura parcial, aislamiento al cambiar credenciales y cero llamadas a red o a
datos productivos. El SDK de cartera sigue sin timeout efectivo; el presupuesto
lógico permite degradar la UI, pero no cancela el socket bloqueado. El p95 real
del navegador no se ha medido.

Ruff completo, NUL 593, `git diff --check`, smoke de imports/parser y validación
local de configuración (23 agentes, 6 tareas) pasan. `kernel-status` en un
`DATA_DIR` temporal da `unsealed` porque no se copia el manifiesto productivo; no
se usa como diagnóstico del kernel vivo. La fecha de despliegue solo queda
disponible tras el recibo verificado. La imagen `.369` de rollback aún no tiene
el lector web, por lo que la fecha visible durante un rollback sigue pendiente.

## Bloqueo de fullsuite y despliegue

Cuatro intentos de fullsuite se detuvieron después de 1.590 pruebas aprobadas en
`test_multiprocess_append_only_event_has_one_canonical_without_lock`. Los 25
procesos hijos fallaron al importar un archivo temporal del entorno con
`NameError: __args`; la prueba individual pasó dos veces (9,91s y 8,81s). El fallo
se mantuvo al retirar el guard temporal, cambiar el lanzador y pedir ejecución
ampliada. La suite no se marca verde, y no se modifica ni excluye la prueba.

Un `WinError 5` al reemplazar un archivo temporal en la carpeta restringida del
sandbox se clasificó por separado: el mismo test pasó con `--basetemp` dentro del
worktree. Ruff halló un orden de imports incorrecto al integrar los dos cambios;
se corrigió y la batería focal final de 160 pasó. La fullsuite fallida precede a
ese cambio mecánico, por lo que el árbol exacto `.378` aún carece de fullsuite
válida.

No hay imagen `.378`, digest ARM ni smoke ARM. No se ejecutó preflight productivo
actual. El último dato documentado es `.321` del 23 de octubre; no se afirma que
siga vivo. Antes de desplegar quedan una fullsuite verde del árbol final, smoke
aislado de ejecución con proveedores locales, QA ARM bajo el límite de 2 GiB,
preflight de quietud/sesión terminal/configuración/kernel y validación de la fecha
en la web. La automatización del 23 de octubre sigue pausada. No se activó la
política de mayor tamaño, ampliaciones ni puntuación.
