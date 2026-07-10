# P-L21 - Diagnostico fiable de servicios

Fecha: 2026-07-10. Version: 0.4.144.

## Problema

Windows PowerShell 5.1 rechazaba `scripts/check_services.ps1` en la linea que
intentaba encadenar directamente un bloque `foreach` a `Format-Table`, con el
error `EmptyPipeElement`. El reinicio y los servicios funcionaban, pero el helper
de diagnostico no podia emitir su veredicto final.

## Solucion

- Materializar las filas de procesos en `$processRows` mediante `@(...)`.
- Pasar despues la coleccion a `Format-Table`.
- Añadir una prueba que analiza el fichero con el parser real de Windows
  PowerShell y comprueba que las filas se materializan antes del formato.

## Alcance y seguridad

No se modifican trading, scheduler, broker, riesgo, configuracion ni `.env`. El
cambio solo afecta a la salida de una herramienta de diagnostico de solo lectura.

## Aceptacion

- El parser PowerShell no devuelve errores.
- El helper real completa y emite `OK: sistema sano` cuando lock, procesos y HTTP
  son coherentes.
- Suite completa, Ruff, no-NUL, gates operativos y smoke aislado verdes.
