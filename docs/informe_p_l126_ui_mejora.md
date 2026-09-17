# P-L126 — catalogo v4.1 y linea Mejora hoy en UI (Jetson 0.4.299 / Windows 0.4.231)

## Causa

- El Selector LLM no listaba `deepseek-v4.1-flash`: con el valor real fuera
  del catalogo, el desplegable mostraba `glm-5.2` (indice 0) y guardar
  habria sobrescrito el v4.1. Anadido al catalogo `opencode-go` y a la
  tabla de modelos probe.
- "Mejora de hoy" solo existia en el markdown del digest, sin superficie UI:
  anadida como caption en el panel Autonomia (usa `state["improvement"]`,
  ya colectado; sin llamadas nuevas).

## Despliegue

- Jetson `0.4.299-arm64` (incremental sobre 0.4.298): patch limpio 3/3,
  smoke con import de `web_app` + parser + catalogo. Salud 1 y 2,
  200/200, scheduler 0.4.299 verificado en vivo.
- Windows 0.4.231 espejo (standby frio). Nota de versiones: la linea Jetson
  (0.4.29x) y la Windows (0.4.23x) avanzan en paralelo; el contenido P-L126
  es identico en ambas.
