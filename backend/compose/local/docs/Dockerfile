# define an alias for the specific python version used in this file.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS python


# Python build stage
FROM python AS python-build-stage

ARG APP_HOME=/app

WORKDIR ${APP_HOME}

RUN apt-get update && apt-get install --no-install-recommends -y \
  # dependencies for building Python packages
  build-essential \
  # psycopg dependencies
  libpq-dev \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

# Requirements are installed here to ensure they will be cached.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project

COPY . ${APP_HOME}

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync


# Python 'run' stage.
# Use the plain slim Python image (not the uv builder image) — uv is only needed
# to build the venv in the build stage; the runtime just needs the interpreter.
# Same build->run base swap the production Django image uses, so the copied
# .venv stays compatible.
FROM python:3.14-slim-bookworm AS python-run-stage

ARG BUILD_ENVIRONMENT
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install --no-install-recommends -y \
  # To run the Makefile
  make \
  # psycopg dependencies
  libpq-dev \
  # Translations dependencies
  gettext \
  # Uncomment below lines to enable Sphinx output to latex and pdf
  # texlive-latex-recommended \
  # texlive-fonts-recommended \
  # texlive-latex-extra \
  # latexmk \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

# copy the built virtualenv from python-build-stage
# (runs as root — local docs server only; the slim base has no dedicated user)
COPY --from=python-build-stage /app /app

COPY ./compose/local/docs/start /start-docs
RUN sed -i 's/\r$//g' /start-docs
RUN chmod +x /start-docs

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /docs
