FROM python:3.12-slim

WORKDIR /app

# Install dependencies and curl for downloading Tailwind CLI
RUN apt-get update -o Acquire::ForceIPv4=true \
    && apt-get install -y --no-install-recommends -o Acquire::ForceIPv4=true curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download Tailwind CSS standalone CLI v3.4.17
RUN curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
    && chmod +x tailwindcss-linux-x64 \
    && mv tailwindcss-linux-x64 /usr/local/bin/tailwindcss

# Copy Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Compile CSS (this relies on input.css and tailwind.config.js being present)
# Note: In development with mounted volumes, the compiled CSS won't live-update 
# unless tailwind is run in watch mode. For the image, we compile it once.
RUN mkdir -p /app/app/static/css \
    && tailwindcss -i ./app/static/css/input.css -o ./app/static/css/output.css --minify || true

# Unprivileged user
RUN useradd -m -r appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 80
