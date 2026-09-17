# P-L129 — resumen Telegram compacto (Jetson 0.4.304 / Windows 0.4.234 en rama)

## Causa

El resumen repetia el SP500 en 3 lineas (valor, diferencia, referencia),
cambiaba la etiqueta de variacion segun la fuente y listaba todas las
posiciones: largo y confuso.

## Cambio

`format_daily_summary` compacto: una linea por bloque (equity con
delta/importe, SP500 con diferencia en pp y veredicto, abiertas con
agregados + top-3 movers). Sin grupos ni lineas redundantes; limite 4096
con recorte simple. Payload y recibo v2 intactos; tests P-L70
re-escritos al nuevo texto (12 expectativas, misma intencion).

## Despliegue Jetson 0.4.304

- Splice de la funcion sobre el arbol 0.4.303 (la linea Jetson habia
  evolucionado: 93 vs 67 lineas). Smoke con ejemplo realista.
- Salud 1+2, 0 reinicios/OOM. Ejemplo: 210 caracteres frente a ~600.
