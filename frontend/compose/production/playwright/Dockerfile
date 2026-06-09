# Playwright E2E runner (production / CI smoke tests).
#
# Unlike the local image, the test suite is baked in (no bind mount): this image
# runs the suite against an already-deployed target — a staging URL or the live
# site — as a post-deploy smoke check. Browsers + OS deps come from the official
# Playwright image.
#
# IMPORTANT: pin this tag to the EXACT `@playwright/test` version in package.json
# (e.g. v1.50.1). A mismatch makes Playwright refuse to launch the browsers.
FROM mcr.microsoft.com/playwright:v1.50.1-noble

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV CI=true

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Bake the project in (tests, playwright.config, etc.). .dockerignore keeps
# node_modules, .next, .git and .envs out of the image.
COPY . .

COPY ./compose/production/playwright/start /start
RUN sed -i 's/\r$//g' /start \
  && chmod +x /start

ENTRYPOINT ["/start"]
