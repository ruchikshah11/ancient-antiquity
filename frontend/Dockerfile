# Ancient Antiquity web app: build the React site, then serve it with nginx.
# Build:  docker build -t ancient-antiquity-web ./frontend
# Normally built and started by ../docker-compose.yml.

# ---- 1. build ----
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Leave empty to call the API on the same domain (/api), which is what nginx below expects.
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}
RUN if [ -z "$VITE_API_URL" ]; then unset VITE_API_URL; fi && npm run build

# ---- 2. serve ----
FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /var/www/certbot /srv/media
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
