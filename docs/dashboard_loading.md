# Carga del Dashboard (0.1.7)

## Diagnostico

El Dashboard esperaba todas las lecturas remotas antes de dibujar el resumen:

1. `alpaca_portfolio_snapshot`: cuenta, posiciones y ordenes (3 peticiones).
2. `build_trade_history`: otra vez cuenta, posiciones y ordenes, mas fills (4).
3. `alpaca_portfolio_history`: serie del grafico (1).

En total, 8 peticiones encadenadas. Cambiar el rango del grafico repetia estas
lecturas. Ademas, `_store` recorria informes, logs y cache para limpiar archivos
en cada render; `store.status()` volvia a inicializar el esquema y contaba todas
las tablas solo para mostrar el numero de ordenes.

Esta estructura explica una espera acumulada y es compatible con la demora
observada de unos 40 segundos. No se ha medido el servidor desplegado ni la
latencia real de la cuenta Alpaca: no se ha accedido a esa cuenta durante el estudio.
El arranque de la importacion web local, tras reparar errores de sintaxis
preexistentes, se midio en 3,88 segundos; no equivale al arranque del servidor.

## Correccion

- Cartera, fills y serie del grafico se consultan en paralelo, con clientes
  independientes. El historico reutiliza la cartera y los fills recibidos:
  5 peticiones en total, sin duplicar la cartera.
- Las lecturas se ejecutan en segundo plano sin llamadas a Streamlit desde los
  trabajadores. La actividad y ordenes locales se muestran durante la espera.
- La cartera se publica en cuanto llega, aunque operaciones o grafico sigan
  pendientes. Los indicadores de P/L no disponibles aparecen como `-`.
- Cada sesion conserva su ultimo resultado y admite una sola carga en curso.
  Cambiar el rango del grafico reutiliza esos datos. La cache se invalida si cambia
  la configuracion; no se comparte entre cuentas o sesiones.
- Los refrescos automaticos respetan el intervalo seleccionado. Con el refresco
  desactivado, la carga inicial sigue completandose mediante sondeo de 1 segundo;
  despues se conserva el resultado hasta pulsar Refrescar. El sondeo rapido se
  detiene cuando termina la carga.
- Durante una actualizacion se mantiene el ultimo resumen visible. Si falla la
  cartera, se conservan los datos anteriores y su fecha. Los errores se muestran
  y puede reintentarse. Tras 10 segundos se avisa de la lentitud del broker.
- La cabecera muestra la fecha de los datos y la duracion de la ultima carga.
- El acceso web inicializa SQLite una vez por sesion y deja de contar todas las
  tablas. La limpieza de archivos sale de la ruta de renderizado; siguen disponibles
  los puntos de mantenimiento existentes del CLI y del arranque del scheduler.

La disponibilidad final sigue dependiendo de Alpaca. El cambio evita que una
peticion lenta bloquee la interfaz, pero no acorta los tiempos de respuesta del
servicio externo ni modifica las llamadas usadas para ejecutar operaciones.

## Verificacion

Con un broker simulado que tarda 200 ms por peticion, usando el mismo SQLite y
los calculos reales del historico:

| Medida | Antes | Despues |
| --- | ---: | ---: |
| Peticiones remotas | 8 | 5 |
| Carga completa | 1,627 s | 0,606 s |

Es una reduccion aproximada del 63% en esa simulacion, no una estimacion del tiempo
en produccion. El cambio tambien permite mostrar contenido local antes de acabar
las consultas, y la cartera antes de acabar el historico/grafico.

Las pruebas cubren concurrencia real con una barrera, ausencia de llamadas
duplicadas, fills vacios, errores parciales, conservacion de la cartera previa,
una sola carga en curso y cache con refresco desactivado. Streamlit AppTest cubre
la pantalla inicial con el broker detenido, la publicacion parcial de cartera,
la pantalla completa, el cambio de rango y el refresco manual.

Resultado: 319 pruebas pasan y 1 se omite porque requiere una base historica local
de pre-earnings que no esta disponible. `compileall` y `git diff --check` pasan.
Se repararon tambien los errores de sintaxis que impedian importar config,
runtime y web_app, una llamada obsoleta en un test de cabeceras LLM y la escritura
invalida de una clave de widget al pulsar Refrescar.

Los cambios estan en el checkout local; no se ha realizado un despliegue.
