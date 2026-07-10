# P-L19 - Fabrica de evidencia y caducidad de diffs

Fecha: 2026-07-10. Version: 0.4.142.

## Resultado

- Contrato obligatorio para propuestas nuevas: clase, hipotesis, evidencia,
  metrica, baseline, target, ventana, muestra, rutas y rollback.
- Gate determinista antes de codegen para contratos incompletos, rutas ausentes o
  prohibidas, evidencia con mas de 30 dias, impacto vago y relajacion de seguridad.
- Digest con clasificacion de experimentos historicos al leer: evidencia,
  comprobaciones operativas y fallos. No se migran ni completan filas antiguas.
- Procedencia de diff con commit y version base, hashes de targets y timestamp.
  TTL de 24 horas; una regeneracion y rechazo en el segundo fallo de frescura.
- Dos propuestas admitidas por dia, WIP dos y un unico codegen nocturno.
- Autonomia de codigo: solo suma impacto post-aplicacion `PASSED` de trading,
  fiabilidad u observabilidad. Docs, tests y digest no suman.
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` sigue siendo condicion obligatoria; el
  runtime conserva una prueba que impide invocar el aplicador autonomo en ese modo.

Linea base real leida tras la entrega: 525 experimentos historicos se clasifican
en 87 `evidence_experiments`, 346 `operational_checks` y 92 `failed_runs`. En las
200 propuestas mas recientes, 0 cumplen todavia el contrato nuevo; esta cifra es
la linea base honesta desde la que debe alcanzarse el objetivo de 70%. No hay
ningun diff vigente presentado para aprobacion humana.

## Compatibilidad y seguridad

No se han modificado kernel, broker, execution, risk, config.py ni .env. Los
registros historicos incompletos se conservan tal cual y solo se etiquetan en la
lectura. El apply de codigo continua requiriendo el CLI humano.

## Verificacion

- Pruebas especificas de contrato, clasificacion, cupos, caducidad por hash y
  doble obsolescencia.
- Suite completa y Ruff limpio antes del commit.
- Gates operativos y smoke aislado se registran en la aceptacion del lote.
