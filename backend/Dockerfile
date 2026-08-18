FROM python:3.12-slim

WORKDIR /app

# Sans PYTHONUNBUFFERED, stdout est bufferise par blocs : les logs
# n'apparaissent dans `podman logs` qu'avec plusieurs minutes de retard,
# ce qui rend le diagnostic d'incident impraticable.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update -o Acquire::ForceIPv4=true \
    && apt-get install -y --no-install-recommends -o Acquire::ForceIPv4=true \
       gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -r appuser && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000 8001 8002
