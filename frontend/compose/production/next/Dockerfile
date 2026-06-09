FROM docker.io/node:26.3.0-bookworm-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install --no-install-recommends -y \
  ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.34.1

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM docker.io/node:26.3.0-bookworm-slim AS builder

WORKDIR /app

RUN npm install -g pnpm@10.34.1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# No default here — NEXT_PUBLIC_API_URL is supplied as a build arg by
# docker-compose.production.yml (a raw `docker build` must pass --build-arg).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN pnpm run build

FROM docker.io/node:26.3.0-bookworm-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 --ingroup nodejs nextjs

COPY ./compose/production/next/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/production/next/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENTRYPOINT ["/entrypoint"]
CMD ["/start"]
