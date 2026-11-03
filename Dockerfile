# ELLOMAX · Controle de contratos e ordens de serviço
# Build pack "Dockerfile" no Coolify. Monte um volume persistente em /data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LICITACOES_DATA=/data \
    PORT=5000 \
    TZ=America/Sao_Paulo

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown -R app:app /data /app
USER app

VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://localhost:${PORT}/saude || exit 1
CMD ["python", "app.py"]
