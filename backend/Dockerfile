FROM python:3.12-slim

WORKDIR /app

#RUN apt-get update && apt-get install -y --no-install-recommends \
#    gcc libpq-dev \
#    && rm -rf /var/lib/apt/lists/*
RUN apt-get update -o Acquire::ForceIPv4=true \
    && apt-get install -y --no-install-recommends -o Acquire::ForceIPv4=true \
       gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8001 8002
