# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS dependencies
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

FROM dependencies AS development
COPY --chown=node:node . .
# Browser requests stay on the frontend origin; Vite proxies /api to the API service.
ENV VITE_API_BASE_URL=""
EXPOSE 8080
CMD ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]

FROM dependencies AS build
COPY --chown=node:node . .
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
