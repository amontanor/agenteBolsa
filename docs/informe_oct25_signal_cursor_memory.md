# Corrección mínima del pico al leer señales — .380

Dictamen: ready_for_integration_rehearsal; no certifica memoria ARM ni despliegue.
Base exacta c2f4b79b2ea29857a61b047243bbc5088ba8cad8 (.379).
Store.signal_outcomes conserva SQL, orden, filtros, límites y contenido íntegro.
Decodifica iterando cursor cerrado determinísticamente en vez de conservar
fetchall junto a la lista completa decodificada. No proyección, truncamiento,
reescritura de features, esquema nuevo ni cambio de autoridad de trading.

Validación focal:54passed6.88s (lector/counterfactual/signal_learning), Ruff
src/tests completo verde, NUL594 y diff verdes. WinError5 del temporal sandbox
reproducido en reportes; nueva ejecución con basetemp del worktree pasa.

Medición sintética aislada:2000filas con8KiB de padding, mismo Store temporal,
función original obtenida del AST de la base y función candidata. Pico Python
tracemalloc original36931101bytes/candidato19799088bytes. Hash JSON completo
idéntico9226ae23f96bff48f6e9e826e1479c8a33c99d9cc764f44d48bca7ac7a3e0e7b.
Es memoria Python del lector, no RSS ni garantía de la ruta completa a200k.
El resultado sigue siendo una lista con features completas; cohortes conservan
retenciones O(N). No afirmar que desapareció el OOM hasta nueva carga ARM
200k/padding8192/2GiB instrumentada y paridad de reportes/persistencia.

Fuentes protegidas/configuración/producción intactas. Fullsuite final y ARM
corresponden al coordinador tras integrar. No ejecutar otro corte paralelo.
