FROM docker.io/node:26.3.0-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install --no-install-recommends -y \
  ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.34.1

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./compose/local/next/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/next/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=development

ENTRYPOINT ["/entrypoint"]
CMD ["/start"]
