# ─── Build Stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# GDAL e dependências nativas do Fiona/Shapely
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ─── Runtime Stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-c1v5 \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Usuário não-root para segurança
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

# Copia site-packages instalados no builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8001

# Limite de recursos conforme SDD seção 4: 1.0 GB RAM | 0.5 vCPU
# --workers 2: 1 worker ativo + 1 em standby dentro do half-vCPU
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
