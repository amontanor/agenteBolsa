"""User-facing command catalog."""

from __future__ import annotations

from typing import Any


def available_command_catalog() -> list[dict[str, Any]]:
    """Return operational commands grouped by common task."""

    return [
        {
            "group": "desatendido",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main schedule",
            "description": "Lanza el sistema desatendido: vigilancia, scan tecnico intradia, candidatos, ciclos LLM y auto paper trading.",
        },
        {
            "group": "desatendido",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main schedule --skip-crew",
            "description": "Lanza el sistema sin LLM: util para comprobar scan, logs y tiempos sin coste de razonamiento.",
        },
        {
            "group": "web",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main web",
            "description": "Abre el panel web local con dashboard, cartera, historico, aprendizaje, backtest, logs y comandos.",
        },
        {
            "group": "estado",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main status",
            "description": "Estado de configuracion, modo paper/live, universo y contadores SQLite.",
        },
        {
            "group": "estado",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main broker-status",
            "description": "Comprueba conexion con Alpaca paper y datos basicos de cuenta.",
        },
        {
            "group": "cartera",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status",
            "description": "Lee cash, equity, buying power, posiciones y ordenes abiertas en Alpaca.",
        },
        {
            "group": "cartera",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main trade-history",
            "description": "Historico desde 2026-04-01, ordenado de antiguo a nuevo, con resumen global final.",
        },
        {
            "group": "cartera",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main trade-history --from 2026-04-01 --json",
            "description": "Mismo historico en JSON para inspeccion detallada o automatizacion.",
        },
        {
            "group": "aprendizaje",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main learning-status --update",
            "description": "Actualiza resultados de senales y resume que indicadores estan funcionando mejor o peor.",
        },
        {
            "group": "aprendizaje",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main learning-review",
            "description": "Crea memoria enriquecida de operaciones, evalua reglas shadow y muestra aprendizaje operativo.",
        },
        {
            "group": "aprendizaje",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main learning-review --with-llm",
            "description": "Pide al LLM nuevas reglas candidatas en shadow mode a partir de resultados reales.",
        },
        {
            "group": "aprendizaje",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main adaptive-tune",
            "description": "Genera propuestas shadow de parametros adaptativos segun evidencia acumulada.",
        },
        {
            "group": "aprendizaje",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main adaptive-status",
            "description": "Muestra parametros adaptativos propuestos/activos y sus motivos.",
        },
        {
            "group": "logs",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 50",
            "description": "Muestra eventos recientes resumidos.",
        },
        {
            "group": "logs",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main log --follow",
            "description": "Sigue eventos en vivo desde otra consola.",
        },
        {
            "group": "logs",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 100 --all-events",
            "description": "Muestra eventos internos y detalle ampliado.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main study-symbol AAPL",
            "description": "Estudio completo de un simbolo: tecnico, figuras, riesgo, fuerza relativa y fundamentales.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main study-symbol AAPL --with-news",
            "description": "Estudio completo de un simbolo incluyendo noticias recientes sin validacion LLM.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main scan-technical --force",
            "description": "Escaneo tecnico amplio del universo configurado, aunque el mercado este abierto.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main breakout-scan",
            "description": "Detecta rupturas o posibles rupturas de resistencia y las clasifica por riesgo sin comprar automaticamente.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main backtest --symbol AAPL --from 2024-01-01",
            "description": "Backtest long-only de la regla tecnica actual con stop/take, time stop, costes y slippage.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main post-market-review",
            "description": "Revisa operaciones tras cierre, muestra resumen de aciertos/errores y guarda aprendizaje para la siguiente sesion.",
        },
        {
            "group": "analisis",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main post-market-review --json",
            "description": "Misma revision post-mercado con operaciones evaluadas, mejoras y guia completa en JSON.",
        },
        {
            "group": "analisis",
            "command": r"Measure-Command { .\.venv\Scripts\python.exe -m agente_bolsa.main scan-technical --force --quiet }",
            "description": "Mide cuanto tarda el escaneo tecnico amplio.",
        },
        {
            "group": "llm",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main decide-once --top-per-side 5",
            "description": "Pide recomendaciones LLM sobre los ultimos candidatos tecnicos y crea planes dry-run.",
        },
        {
            "group": "cartera",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main rebalance-status --top-per-side 5",
            "description": "Muestra contexto de rebalanceo: posiciones, candidatos, rotaciones y costes, sin operar.",
        },
        {
            "group": "scheduler",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status",
            "description": "Muestra calendario de mercado y jobs configurados.",
        },
        {
            "group": "scheduler",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main job-once market --skip-crew",
            "description": "Ejecuta una vez el flujo de mercado con scan tecnico pero sin LLM.",
        },
        {
            "group": "scheduler",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main job-once portfolio",
            "description": "Ejecuta una revision puntual de cartera. Si no hay actividad no imprime nada.",
        },
        {
            "group": "scheduler",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main job-once post-market-review --force",
            "description": "Fuerza la revision post-mercado aunque ya se haya hecho para la sesion.",
        },
        {
            "group": "ejecucion",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main execute-approved --confirm-paper",
            "description": "Envia a Alpaca paper planes aprobados pendientes. No usar sin revisar antes los planes.",
        },
        {
            "group": "ayuda",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main --help",
            "description": "Ayuda nativa del CLI.",
        },
        {
            "group": "ayuda",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main commands",
            "description": "Resumen claro de comandos operativos frecuentes.",
        },
        {
            "group": "ayuda",
            "command": r".\.venv\Scripts\python.exe -m agente_bolsa.main commands --json",
            "description": "Catalogo completo de comandos en JSON.",
        },
    ]


def command_cheatsheet() -> str:
    """Return a compact human-readable operational cheatsheet."""

    return "\n".join(
        [
            "AGENTE BOLSA - COMANDOS CLAVE",
            "",
            "1) Lanzar el sistema desatendido",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main schedule",
            "   Ejecuta vigilancia, scan tecnico intradia, seleccion de candidatos, ciclo LLM y auto paper trading.",
            "   En modo paper puede comprar/vender automaticamente si el LLM y el riesgo aprueban la operacion.",
            "",
            "2) Abrir panel web local",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main web",
            "   Dashboard local para cartera, ordenes, motivos, historico, aprendizaje, backtests, logs y comandos.",
            "",
            "3) Ver estado general",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main status",
            "   Comprueba modo paper/live, broker, universo y contadores de eventos/ordenes.",
            "",
            "4) Ver cartera Alpaca paper",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status",
            "   Muestra cash, equity, buying power, posiciones y ordenes abiertas.",
            "",
            "5) Ver historico compra/venta y ganancias/perdidas",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main trade-history",
            "   Muestra fills desde 2026-04-01, P/L realizado, P/L abierto y resumen global actual.",
            "",
            "6) Ver aprendizaje de senales",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main learning-status --update",
            "   Actualiza outcomes y muestra mejores/peores indicadores por resultado posterior.",
            "",
            "7) Ver/proponer ajuste adaptativo",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main learning-review --with-llm",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main adaptive-tune",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main adaptive-status",
            "   Crea memoria operativa, reglas shadow y propone cambios conservadores; no toca .env.",
            "",
            "8) Ver log resumido",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 50",
            "   Resume que ha hecho el sistema sin leer archivos grandes.",
            "",
            "9) Seguir log en vivo desde otra consola",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main log --follow",
            "   Util mientras schedule sigue corriendo en otra ventana.",
            "",
            "10) Analizar un simbolo completo",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main study-symbol AAPL",
            "   Tecnico, figuras, riesgo, fuerza relativa contra SPY y fundamentales.",
            "",
            "11) Analizar un simbolo con noticias",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main study-symbol AAPL --with-news",
            "   Anade noticias recientes sin llamar al LLM.",
            "",
            "12) Escanear muchos simbolos ahora",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main scan-technical --force",
            "   Escanea el universo configurado aunque el mercado este abierto.",
            "",
            "13) Detectar rupturas de resistencia",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main breakout-scan",
            "   Busca rupturas confirmadas o inminentes y marca si son operables o demasiado arriesgadas.",
            "",
            "14) Backtest de la regla tecnica actual",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main backtest --symbol AAPL --from 2024-01-01",
            "   Simula entradas long strong, stop/take por ATR, time stop, costes y slippage.",
            "",
            "15) Revision post-mercado y aprendizaje",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main post-market-review",
            "   Evalua compras/ventas del dia, muestra que aprendio, propone mejoras minimas y guarda aprendizaje para la siguiente sesion.",
            "",
            "16) Medir cuanto tarda el scan",
            r"   Measure-Command { .\.venv\Scripts\python.exe -m agente_bolsa.main scan-technical --force --quiet }",
            "   Devuelve la duracion real del analisis tecnico amplio.",
            "",
            "17) Pedir decision LLM dry-run",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main decide-once --top-per-side 5",
            "   Genera recomendaciones de mantener/reducir/vender/rotar/comprar y planes teoricos; no compra.",
            "",
            "18) Ver contexto de rebalanceo sin LLM",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main rebalance-status --top-per-side 5",
            "   Compara posiciones, candidatos, riesgo, coste de rotacion y posibles reemplazos.",
            "",
            "19) Ejecutar planes aprobados en Alpaca paper",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main execute-approved --confirm-paper",
            "   Envia ordenes paper pendientes. Revisar antes status/planes/logs.",
            "",
            "20) Ver catalogo completo en JSON",
            r"   .\.venv\Scripts\python.exe -m agente_bolsa.main commands --json",
            "   Lista estructurada para consultar o automatizar.",
        ]
    )
