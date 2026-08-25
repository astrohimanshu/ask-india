# syntax=docker/dockerfile:1.7
# Ask India web. Build from apps/web:
#   docker build -t ghcr.io/astrohimanshu/ask-india-web:dev --build-arg NEXT_PUBLIC_API_URL=https://api.example apps/web
FROM node:22-alpine AS deps
RUN corepack enable && corepack prepare pnpm@11.24.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
RUN corepack enable && corepack prepare pnpm@11.24.0 --activate
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS runtime
RUN addgroup -S askindia && adduser -S -G askindia -u 10001 askindia
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=builder --chown=askindia:askindia /app/.next/standalone ./
COPY --from=builder --chown=askindia:askindia /app/.next/static ./.next/static
COPY --from=builder --chown=askindia:askindia /app/public ./public
USER askindia
EXPOSE 3000
CMD ["node", "server.js"]
