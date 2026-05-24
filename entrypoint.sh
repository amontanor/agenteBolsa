#!/bin/bash
# entrypoint.sh - Script de inicio multiproceso para el contenedor Docker

# Asegurar que existan todos los directorios requeridos dentro del volumen persistente SSD
echo "==> Asegurando estructura de directorios en el volumen persistente /data..."
mkdir -p /data/state \
         /data/logs \
         /data/logs/agents \
         /data/checkpoints \
         /data/cache \
         /data/hypotheses \
         /data/backtests \
         /data/reports

# Inicializar la base de datos SQLite si no existe en el volumen
if [ ! -f "/data/state/agente_bolsa.sqlite3" ]; then
    echo "==> Base de datos SQLite no encontrada. Inicializando base de datos por primera vez..."
    python -m agente_bolsa.main init-db
else
    echo "==> Base de datos existente detectada en /data/state/agente_bolsa.sqlite3."
fi

# Arrancar el planificador recurrente de tareas en segundo plano
echo "==> Arrancando el planificador autónomo (scheduler.py) en segundo plano..."
python -m agente_bolsa.main schedule &
SCHEDULER_PID=$!

# Función para detener procesos al recibir señales del sistema (apagado correcto)
graceful_shutdown() {
    echo "==> Señal de parada recibida. Apagando planificador (PID $SCHEDULER_PID)..."
    kill -TERM "$SCHEDULER_PID" 2>/dev/null
    exit 0
}

# Registrar la función de parada para señales SIGINT y SIGTERM
trap graceful_shutdown SIGINT SIGTERM

# Arrancar la interfaz web de Streamlit en primer plano como proceso principal (PID 1)
echo "==> Arrancando el Dashboard de Streamlit en el puerto 8080..."
exec streamlit run src/agente_bolsa/web_app.py --server.port 8080 --server.address 0.0.0.0
