# ============================================================
# SentryPass — Frontend (TanStack Start / Nitro node-server)
# ============================================================

# ── Build ──
FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lock bunfig.toml ./
RUN bun install --frozen-lockfile

COPY . .

# VITE_API_URL é embutido no bundle do cliente em BUILD-TIME.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

# Build com Nitro preset node-server → gera .output/server/index.mjs
RUN bun run build:docker

# ── Runtime ──
# Nitro empacota tudo em .output (não precisa de node_modules).
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

COPY --from=build /app/.output ./.output

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
