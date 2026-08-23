# ─── Étape 1 : build de la SPA ───
FROM node:22-alpine AS build

WORKDIR /app

# Les dépendances sont installées avant la copie du code : tant que
# package.json ne change pas, cette couche est réutilisée telle quelle.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .

# Les variables VITE_* sont inlinées à la compilation, pas lues au runtime.
ARG VITE_API_BASE_URL=""
ARG VITE_WS_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_URL=$VITE_WS_URL

RUN npm run build

# ─── Étape 2 : service du build statique ───
FROM nginx:alpine AS runtime

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# Adresse littérale plutôt que `localhost` : la sonde ne doit pas dépendre
# de l'ordre de résolution IPv6/IPv4 de l'image de base.
# Podman ignore cette instruction en format OCI ; compose.yml redéfinit la
# même sonde, qui est celle réellement appliquée par la stack.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
