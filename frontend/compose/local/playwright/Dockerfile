# Playwright E2E runner (local).
#
# Microsoft's official Playwright image ships the browsers AND their OS-level
# dependencies pre-installed, so there is no `playwright install` step and no
# apt browser deps to maintain.
#
# IMPORTANT: pin this tag to the EXACT `@playwright/test` version in
# package.json (e.g. v1.50.1). A mismatch makes Playwright refuse to launch the
# bundled browsers.
#
# To actually use this:
#   1. Add `@playwright/test` to package.json devDependencies + a playwright.config.ts
#   2. Set the tag below to that version
#   3. Wire a `playwright` service into docker-compose.local.yml (example at the
#      bottom of that file)
FROM mcr.microsoft.com/playwright:v1.50.1-noble

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
# Browsers live here in the base image; keep the test runner pointed at them.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV CI=true

RUN corepack enable

# Install JS deps in the image. The compose bind mount keeps the source live
# while an anonymous /app/node_modules volume protects these container-built deps.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./compose/local/playwright/start /start
RUN sed -i 's/\r$//g' /start \
  && chmod +x /start

ENTRYPOINT ["/start"]
