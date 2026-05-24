# Utilizar una imagen oficial de Python slim para compilar rápido y reducir el tamaño
FROM python:3.11-slim

# Evitar que Python escriba archivos .pyc en el disco
ENV PYTHONDONTWRITEBYTECODE=1
# Evitar que Python almacene en búfer stdout y stderr para ver logs en tiempo real
ENV PYTHONUNBUFFERED=1
# Desactivar avisos interactivos de Debian
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Instalar dependencias del sistema necesarias para construir ciertas extensiones de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copiar ficheros de dependencias primero para aprovechar la caché de Docker
COPY requirements.txt pyproject.toml ./

# Instalar dependencias de Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente y el resto del proyecto
COPY . .

# Instalar el propio paquete en modo editable o normal
RUN pip install --no-cache-dir -e .

# Crear el directorio de datos donde se montará el volumen persistente SSD
RUN mkdir -p /data

# Definir la variable de entorno para que el bot use /data como su almacén persistente
ENV DATA_DIR=/data

# Hacer ejecutable el script de entrada
RUN chmod +x /app/entrypoint.sh

# Exponer el puerto predeterminado que usará Streamlit
EXPOSE 8080

# Usar el script entrypoint para arrancar el scheduler y Streamlit simultáneamente
ENTRYPOINT ["/app/entrypoint.sh"]
