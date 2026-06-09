<div align="center">

# DjangoNext

### A production-ready Django + Next.js full-stack starter template

A production-ready, fully-containerized **full-stack monorepo** — a **Django 6 / DRF**
API backend and a **Next.js 16 / React 19** frontend, wired together and ready to ship.

<p>
  <img alt="Python 3.14" src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white">
  <img alt="Django 6.0" src="https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white">
  <img alt="DRF" src="https://img.shields.io/badge/DRF-OpenAPI_3-A30000?logo=fastapi&logoColor=white">
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white">
  <img alt="React 19" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black">
  <img alt="TypeScript 5" src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white">
  <img alt="Tailwind CSS 4" src="https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white">
</p>
<p>
  <img alt="PostgreSQL 18" src="https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white">
  <img alt="Redis" src="https://img.shields.io/badge/Redis-cache_%2F_broker-DC382D?logo=redis&logoColor=white">
  <img alt="Celery 5.6" src="https://img.shields.io/badge/Celery-5.6-37814A?logo=celery&logoColor=white">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose_v2-2496ED?logo=docker&logoColor=white">
  <img alt="Traefik" src="https://img.shields.io/badge/Traefik-TLS_edge-24A1C1?logo=traefikproxy&logoColor=white">
</p>
<p>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <a href="https://github.com/cookiecutter/cookiecutter-django/"><img alt="Built with Cookiecutter Django" src="https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter"></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
  <img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg">
</p>

<p>
  <b>
  <a href="#quick-start-docker">Quick Start</a> &nbsp;·&nbsp;
  <a href="#architecture">Architecture</a> &nbsp;·&nbsp;
  <a href="#security">Security</a> &nbsp;·&nbsp;
  <a href="#common-commands">Commands</a> &nbsp;·&nbsp;
  <a href="#deployment">Deployment</a>
  </b>
</p>

</div>

<!-- TEMPLATE:DOC:START -->

<div align="center">

## 🍪 You are looking at a *template*

</div>

This repository is a **bootstrappable starter** — it doesn't run as-is. A single script,
[`install.py`](install.py), turns it into *your* project: it replaces the `__TOKEN__`
placeholders, renames the Python package, picks your media backend, generates real `.env`
files with **freshly-generated secrets**, and (optionally) builds and starts the whole stack
for you.

The backend is scaffolded from **[Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django)**
and the frontend from **[create-next-app](https://nextjs.org/docs/app/api-reference/cli/create-next-app)**,
so you inherit two battle-tested project layouts — then `install.py` stitches them into one
cohesive, Dockerized monorepo.

### Use this template

> **You'll need:** [**Python 3.11+**](https://www.python.org/downloads/) (to run the
> installer) · [**Git**](https://git-scm.com/) (to clone) ·
> [**Docker** + Compose v2](https://docs.docker.com/get-docker/) (to run the stack the
> installer offers to start).

Clone the template and enter it:

```bash
git clone https://github.com/vlabeit/DjangoNext.git
cd DjangoNext
```

Then bootstrap your project **one of two ways** — pick the option that fits you:

### Interactive start (CLI prompts)

Let the installer prompt you for each value, then offer to build & start the stack:

```bash
python3 install.py
```

### Or Quick start with a config file (JSON)

Prefer a **reproducible / non-interactive / CI** run? Put your answers in a JSON file and feed
it to the installer with `--config` — no prompts.

**1. Fill in your `user-answers.json`** with your project's values:

```json
{
  "project_name": "DjangoNext",
  "project_slug": "djangonext",
  "domain": "example.com",
  "author_name": "Jane Doe",
  "author_email": "jane@example.com",
  "project_description": "A full-stack Django + Next.js app.",
  "timezone": "UTC",
  "media": "local",
  "start": "dev",
  "destroy": false
}
```

> [!NOTE]
> JSON has **no comments** — keep the file exactly as above (no `//` lines), or the installer's
> strict parser will reject it. Each field is explained here instead:

| Field | Required | What it does |
| --- | :--: | --- |
| `project_name` | ✅ | Human-friendly display name. |
| `project_slug` | ✅ | Python package + Docker image/volume names — lowercase, no spaces. |
| `domain` | ✅ | Production hostname (Traefik routing, env defaults). |
| `author_email` | ✅ | Author credit **and** the Let's Encrypt ACME registration email. |
| `media` | ✅ | `"local"` (filesystem) or `"aws"` (S3 via django-storages). |
| `author_name` | – | Author credit in docs / meta. |
| `project_description` | – | One-line tagline. |
| `timezone` | – | IANA name, e.g. `"UTC"` or `"Asia/Jerusalem"` (default `UTC`). |
| `start` | – | Bring-up after bootstrap: `false`, `"dev"`, or `"prod"`. |
| `destroy` | – | `true` resets this project's DB volume first (**destroys** its data). |

<details>
<summary><b>No editor handy?</b> (headless / Linux CLI) — write the file from the shell</summary>

<br>

Copy-paste this single block to create `user-answers.json`, then run step 2 below:

```bash
cat > user-answers.json <<'JSON'
{
  "project_name": "DjangoNext",
  "project_slug": "djangonext",
  "domain": "example.com",
  "author_name": "Jane Doe",
  "author_email": "jane@example.com",
  "project_description": "A full-stack Django + Next.js app.",
  "timezone": "UTC",
  "media": "local",
  "start": "dev",
  "destroy": false
}
JSON
```

</details>

**2. Run the installer with your config:**

```bash
python3 install.py --config user-answers.json --yes
```

That's it — fully non-interactive. Because `"start": "dev"` is set, it also builds and starts
the dev stack after bootstrapping. CLI flags override the JSON — e.g. target production:

```bash
python3 install.py --config user-answers.json --yes --start --production
```

> `install.py` is **standalone** — it needs only **Python 3.11+** and zero third-party
> packages. See **[TEMPLATE.md](TEMPLATE.md)** for every flag, the full schema, the token
> reference, the media-backend options, and the post-install secrets checklist.

---

<!-- TEMPLATE:DOC:END -->

## What you get out of the box

A complete app skeleton you can demo in minutes and grow into production — no glue code, no
"day-one" wiring, no guessing how the pieces fit.

| | Feature | Details |
| :--: | --- | --- |
| 🔐 | **Authentication** | Sign-up with email verification, **MFA**, and DRF token auth via [django-allauth](https://docs.allauth.org/). |
| 🧩 | **REST API** | DRF with an auto-generated **OpenAPI 3** schema and an interactive **Swagger UI**. |
| ⚙️ | **Background jobs** | Celery workers, scheduled tasks via Beat, and a **Flower** monitoring dashboard. |
| 👤 | **Custom user model** | An extendable `users.User`, ready for your domain — the hard-to-change thing, done right up front. |
| 🔌 | **WebSockets** | A minimal ASGI endpoint, served from the same process as the API — build realtime on top. |
| 🌐 | **CORS** | Pre-configured so the Next.js frontend can call the API on day one. |
| 🐳 | **One-command Docker** | The entire stack — web, API, DB, cache, three Celery services — boots from a single command. |
| 🛡️ | **Hardened production** | Traefik edge with auto-TLS, network isolation, shared security headers, and a rate-limited admin. |
| ✅ | **CI included** | GitHub Actions running pre-commit, frontend lint/type-check/build, and a dockerized pytest suite. |

---

## Contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick start (Docker)](#quick-start-docker)
- [Service URLs](#service-urls)
- [Common commands](#common-commands)
- [Security](#security)
- [Database & migrations](#database--migrations)
- [Managing dependencies](#managing-dependencies)
- [Local development without Docker](#local-development-without-docker)
- [Testing & quality](#testing--quality)
- [Environment variables](#environment-variables)
- [Deployment](#deployment)
- [Project structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Architecture

DjangoNext is a monorepo with two independently deployable services that talk over HTTP.

### Development topology

```
┌──────────────────────────┐         ┌──────────────────────────────┐
│  frontend  (Next.js 16)  │  HTTP   │  backend  (Django 6 / DRF)   │
│  React 19 · TypeScript   │ ──────▶ │  REST API  ·  OpenAPI/Swagger │
│  Tailwind CSS 4          │  /api   │  Auth · WebSockets · Admin    │
└──────────────────────────┘         └───────────────┬──────────────┘
                                                      │
                                  ┌───────────────────┼───────────────────┐
                                  ▼                   ▼                   ▼
                            PostgreSQL 18          Redis            Celery worker
                                                 (broker/cache)     + Beat + Flower
```

The Next.js app is a standalone client that consumes the Django REST API
(`NEXT_PUBLIC_API_URL`). The Django service also ships the admin, allauth account flows,
and a Swagger UI from its Cookiecutter Django base.

<details>
<summary><b>How the backend is wired</b> — ASGI, settings, routing, apps, background work</summary>

<br>

- **ASGI-first.** Both local and production run under Uvicorn workers. `config/asgi.py`
  exposes a single ASGI `application` that dispatches `http` scopes to Django and
  `websocket` scopes to a lightweight handler in `config/websocket.py` — so REST and
  realtime are served from one process, with no separate Channels layer.
- **Settings split by target.** `config/settings/` holds `base.py` (shared) plus
  `local.py`, `production.py`, and `test.py`. The active module is selected via the
  `DJANGO_SETTINGS_MODULE` env var (defaults to `config.settings.local`). Production
  layers on S3 storage, Sentry, Anymail/Mailgun, secure cookies, and Redis caching.
- **URLs & API routing.** `config/urls.py` mounts the admin, allauth, server-rendered
  pages, and the API under `/api/`. `config/api_router.py` registers DRF viewsets on a
  router (browsable `DefaultRouter` in DEBUG, `SimpleRouter` otherwise). drf-spectacular
  generates the OpenAPI 3 schema at `/api/schema/` and the Swagger UI at `/api/docs/`.
- **Apps live under `__PROJECT_SLUG__/`.** Each app keeps its REST layer in an `api/`
  subpackage (`serializers.py`, `views.py`). The bundled `users` app ships a custom user
  model, allauth adapters, a `UserViewSet`, and an example Celery `tasks.py`.
- **Background work.** Celery uses Redis as broker and result backend;
  `django-celery-beat` stores the periodic schedule in the database, and Flower exposes a
  monitoring dashboard.

</details>

### Production topology

In production a **Traefik** reverse proxy terminates TLS and routes by path across two
isolated Docker networks (see [Security](#security)):

```
                          Internet  (:80 → :443)
                                  │
                          ┌───────▼────────┐
                          │    Traefik     │  Let's Encrypt TLS · HTTP→HTTPS
                          │  reverse proxy │  path routing · security headers
                          └───┬────────┬───┘        ──── network: web ────
              /api /admin     │        │  everything
              /static /media  │        │  else
                        ┌─────▼──┐  ┌──▼─────┐
                        │ Django │  │ Next.js│
                        │ :5000  │  │ :3000  │
                        └───┬────┘  └────────┘
       ──── network: backend │ ───────────────────────────────────
                ┌───────────┼────────────┬──────────────────┐
                ▼           ▼             ▼                  ▼
          PostgreSQL 18   Redis    Celery worker/beat   Flower (:5555)
```

`postgres` and `redis` sit only on the internal `backend` network, so the edge can never
reach the data stores directly; only `django` and `flower` bridge both networks.

---

## Tech stack

<table>
<tr><th align="left">Backend (<code>backend/</code>)</th><th align="left">Frontend (<code>frontend/</code>)</th></tr>
<tr valign="top"><td>

| Area | Choice |
| --- | --- |
| Runtime | Python 3.14 |
| Framework | Django 6.0 |
| API | DRF + drf-spectacular (OpenAPI 3) |
| Auth | django-allauth (email verify, MFA) + DRF token |
| Async tasks | Celery 5.6 + Beat, monitored by Flower |
| Database | PostgreSQL 18 (`psycopg`) |
| Cache / broker | Redis (`django-redis`, `hiredis`) |
| Realtime | ASGI WebSocket endpoint (Uvicorn) |
| Email / errors | Anymail (Mailgun), Sentry |
| Static / media | WhiteNoise, django-storages (S3 in prod) |
| Tooling | `uv`, Ruff, mypy, djLint, pytest, pre-commit |

</td><td>

| Area | Choice |
| --- | --- |
| Framework | Next.js 16 (App Router) |
| UI | React 19, Tailwind CSS 4 |
| Language | TypeScript 5 |
| Package manager | pnpm 10 |
| Tooling | ESLint, `tsc` type-checking |

<br>

> **Why two generators?** The backend is scaffolded from Cookiecutter Django and the
> frontend from create-next-app — you inherit two well-maintained, opinionated layouts
> instead of a hand-rolled one. See [Acknowledgements](#acknowledgements).

</td></tr>
</table>

---

## Prerequisites

### To run with Docker (recommended)

- [**Docker Engine**](https://docs.docker.com/get-docker/) with the **Compose v2** plugin (the `docker compose` subcommand)
- [**Git**](https://git-scm.com/) to clone the repository
- ~4 GB of free RAM for the full stack (Postgres, Redis, Django, three Celery services, Next.js)

> [!NOTE]
> Every *application* runtime (Python 3.14, Node) is provided **inside the Docker images** —
> you don't install them on your host. For the Docker path, the host only needs **Docker**
> and **Git**.

### To run natively (without Docker)

| Tool | Version | Purpose |
| --- | --- | --- |
| [Python](https://www.python.org/) | 3.14 | backend runtime (pinned in `backend/.python-version`) |
| [`uv`](https://docs.astral.sh/uv/getting-started/installation/) | latest | Python dependency & virtualenv manager |
| [Node.js](https://nodejs.org/) | 22+ | frontend runtime |
| [`pnpm`](https://pnpm.io/installation) | 10 | frontend package manager |
| [PostgreSQL](https://www.postgresql.org/) | 18 | database |
| [Redis](https://redis.io/) | 7+ | Celery broker / cache (only if running Celery) |
| [`just`](https://github.com/casey/just) | optional | shorthand for the Docker recipes in `backend/justfile` |

---

## Quick start (Docker)

The fastest way to run everything (frontend, API, Postgres, Redis, Celery) is Docker Compose.
For the Docker path you only need Docker (with the Compose plugin) and Git — see
[Prerequisites](#prerequisites).

```bash
# 1. Clone
git clone https://github.com/vlbeit/DjangoNext.git
cd DjangoNext

# 2. Create local env files from the templates (these are gitignored)
cp backend/.envs/.local/.django.example    backend/.envs/.local/.django
cp backend/.envs/.local/.postgres.example  backend/.envs/.local/.postgres
cp frontend/.envs/.local/.next.example     frontend/.envs/.local/.next

# 3. Build and start the full local stack
docker compose -f docker-compose.local.yml up --build
```

The local templates ship with safe, dev-only defaults, so once you've copied them the stack
starts with no further configuration.

Once the containers are healthy, create an admin user in another terminal:

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

---

## Service URLs

| Service | URL |
| --- | --- |
| 🖥️ Frontend (Next.js) | http://localhost:3000 |
| 🔧 Backend (Django) | http://localhost:8000 |
| 📚 API docs (Swagger) | http://localhost:8000/api/docs/ |
| 📐 OpenAPI schema | http://localhost:8000/api/schema/ |
| 🛠️ Django admin | http://localhost:8000/admin/ |
| 🌸 Flower (Celery) | http://localhost:5555 |

> The Django container is published on host port **`8000`** (see `docker-compose.local.yml`).
> The frontend's `NEXT_PUBLIC_API_URL` points there.

---

## Common commands

All commands assume you are at the repo root. Each block is a single command — hover it and
click the **📋 copy** button (top-right of the block) to grab it clean, no comments attached.

### Stack

**Start (foreground):**

```bash
docker compose -f docker-compose.local.yml up
```

**Start (detached / background):**

```bash
docker compose -f docker-compose.local.yml up -d
```

**Stop:**

```bash
docker compose -f docker-compose.local.yml down
```

**Tail logs:**

```bash
docker compose -f docker-compose.local.yml logs -f
```

### Django management

**Apply migrations:**

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

**Create migrations after model changes:**

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py makemigrations
```

**Open a Django shell:**

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py shell
```

**Create a superuser:**

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

### Tests

**Run the test suite:**

```bash
docker compose -f docker-compose.local.yml run --rm django pytest
```

A [`just`](https://github.com/casey/just) recipe file in `backend/justfile` provides
shorthand for these Docker tasks.

---

## Security

Security is wired into the template, not left as an exercise. The defaults below apply to the
**production** stack; the local stack relaxes them for developer ergonomics.

| Area | What's in place |
| --- | --- |
| 🔑 **Secrets** | Real `.env` files are **gitignored** — only `*.example` templates are committed; secrets are **generated fresh at bootstrap**. |
| 🧱 **Network isolation** | `postgres` and `redis` live **only** on the internal `backend` network; Traefik lives only on `web`. The public edge **cannot reach the data stores**. |
| 🔒 **TLS at the edge** | Traefik obtains & renews **Let's Encrypt** certs (ACME HTTP-01), redirects `:80 → :443`, and restricts to a modern **TLS 1.2+** cipher suite. |
| 🛡️ **Security headers** | One shared Traefik middleware stamps **HSTS**, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and **strips the backend `Server` header** on both routers. |
| 🚪 **Admin hardening** | The real admin lives at an obscured `DJANGO_ADMIN_URL`, behind a **rate-limited** router; error pages are **brand-neutral** so they don't fingerprint Django. |
| 👤 **Auth** | allauth **email verification + MFA**, plus DRF token auth. |
| 🌐 **CORS** | Pre-configured for the Next.js origin only. |
| ✅ **Quality gates** | Ruff, mypy, djLint, and pre-commit catch issues before they land; CI runs the same checks. |

> [!WARNING]
> The random `DJANGO_ADMIN_URL` reduces drive-by `/admin` probing, but it is **not** a
> security boundary — `/static/admin/…` and `/api/docs/` still reveal a Django/DRF backend.
> Rely on a **strong admin password** (and consider 2FA via `django-otp`) for real
> protection; the random path + admin rate-limit are defense-in-depth.

> [!IMPORTANT]
> **Traefik is authoritative for public headers.** Because it re-stamps security headers on
> the way out, its values win over Django's for proxied traffic. To change what a browser
> actually receives, edit `backend/compose/production/traefik/dynamic.yml` — changing Django
> settings alone won't affect proxied responses. Full details in
> [Reverse proxy & TLS](#reverse-proxy--tls-traefik).

**Never commit real env files**, and rotate any credential that has ever been exposed. See
[Environment variables](#environment-variables) and the global
[security checklist](https://cookiecutter-django.readthedocs.io/en/latest/3-deployment/deployment-with-docker.html).

---

## Database & migrations

Migrations are committed to the repo (under each app's `migrations/` directory) and should be
regenerated whenever you change a model.

> [!NOTE]
> **In the local Docker stack, migrations are applied automatically on startup** — the Django
> container's `/start` script runs `python manage.py migrate` before launching the server, so a
> fresh `docker compose up` always has an up-to-date schema.

```bash
# Create migrations after changing models
docker compose -f docker-compose.local.yml run --rm django python manage.py makemigrations

# Apply migrations
docker compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

> [!WARNING]
> **Production differs by design.** The production `/start` script does **not** run migrations
> automatically — that avoids multiple app containers racing to apply schema changes. Run them
> as an explicit deploy step:
>
> ```bash
> docker compose -f docker-compose.production.yml run --rm django python manage.py migrate
> ```

Running natively (without Docker), use `uv run python manage.py makemigrations` / `migrate`.

<details>
<summary><b>Troubleshooting:</b> <code>password authentication failed for user …</code></summary>

<br>

This means the Postgres **data volume was initialized with different credentials** than the
ones in your env files. Postgres only applies `POSTGRES_USER` / `POSTGRES_PASSWORD` the first
time it initializes an empty data directory — once the volume exists it keeps its original
credentials and ignores new ones. You'll see this if you re-run the installer (it generates
fresh random credentials each run) or change `POSTGRES_PASSWORD` after the stack has already
started once.

Fix it by resetting the database volume so it re-initializes with the current credentials.
**This destroys the database's data** (fine for local/dev):

```bash
# Pick the compose file for the affected stack (.local or .production)
docker compose -f docker-compose.local.yml down
docker volume ls | grep postgres_data          # find this project's volumes
docker volume rm <name> <name>_backups         # e.g. myproj_local_postgres_data[_backups]
docker compose -f docker-compose.local.yml up --build
```

To keep the data instead, set `POSTGRES_USER` / `POSTGRES_PASSWORD` in your env files back to
the values the volume was created with, or `ALTER USER` inside the running database.

</details>

---

## Managing dependencies

<details>
<summary><b>Backend</b> — <code>uv</code> &amp; the committed <code>uv.lock</code></summary>

<br>

The backend uses [`uv`](https://github.com/astral-sh/uv) with a committed
**`backend/uv.lock`** lockfile that pins exact, hash-verified versions for reproducible
builds. Don't edit `uv.lock` by hand — regenerate it from `pyproject.toml`. To add or change a
Python dependency:

1. Edit `backend/pyproject.toml` — add the pin to `dependencies` (or to the `dev` group under
   `[dependency-groups]`), e.g. `"some-package==1.2.3"`.
2. Regenerate the lockfile:
   ```bash
   docker compose -f docker-compose.local.yml run --rm django uv lock
   ```
3. Rebuild the image so the dependency is baked in — containers are ephemeral, so a bare
   `uv add` inside a running one would not persist:
   ```bash
   docker compose -f docker-compose.local.yml build
   docker compose -f docker-compose.local.yml up
   ```

Working natively instead? `uv add some-package==1.2.3` updates `pyproject.toml` and `uv.lock`
together, and `uv sync` installs exactly what the lockfile specifies. Always commit
`pyproject.toml` and `uv.lock` together.

</details>

<details>
<summary><b>Frontend</b> — <code>pnpm</code> &amp; <code>pnpm-lock.yaml</code></summary>

<br>

Frontend dependencies are managed with **pnpm**; `frontend/pnpm-lock.yaml` is the committed
lockfile. Use `pnpm add <pkg>` to add a dependency and `pnpm install` to sync.

</details>

---

## Local development without Docker

You can also run each side natively.

<details>
<summary><b>Backend</b></summary>

<br>

Uses [`uv`](https://github.com/astral-sh/uv) for dependency and environment management (see
[Prerequisites](#prerequisites) for the full tool list). Requires a local PostgreSQL and, if
you run Celery, Redis.

```bash
cd backend
uv sync                                   # install exactly what uv.lock pins
uv run python manage.py migrate
uv run python manage.py runserver         # or: uv run uvicorn config.asgi:application --reload
```

Point Django at your database with the `DATABASE_URL` env var, e.g.
`export DATABASE_URL=postgres://postgres:<password>@127.0.0.1:5432/__PROJECT_SLUG__`. To run
background jobs, start Redis and a worker in a separate terminal:
`uv run celery -A config.celery_app worker -l info`.

</details>

<details>
<summary><b>Frontend</b></summary>

<br>

```bash
cd frontend
pnpm install
pnpm dev                                  # http://localhost:3000
```

</details>

---

## Testing & quality

```bash
# Backend — tests with coverage
cd backend
uv run coverage run -m pytest
uv run coverage html        # report at htmlcov/index.html

# Backend — types and linting
uv run mypy __PROJECT_SLUG__
uv run ruff check .

# Frontend — lint, type-check, build
cd frontend
pnpm run lint
pnpm run typecheck
pnpm run build
```

Pre-commit hooks (Ruff, djLint, and more) run automatically on commit:

```bash
cd backend
uv run pre-commit install
```

---

## Environment variables

Environment files live under each service's `.envs/` directory, split by target (`.local/`
and `.production/`). **Real env files are gitignored** — only `*.example` templates are
committed. Copy each template to its real filename and fill it in:

```
backend/.envs/.local/.django.example    →  .django
backend/.envs/.local/.postgres.example  →  .postgres
frontend/.envs/.local/.next.example     →  .next
# production equivalents live under .envs/.production/
```

- **`.local/`** templates contain safe, dev-only defaults — copy them and you're ready to go.
- **`.production/`** templates contain placeholders — fill in real secrets before deploying.
  See the Cookiecutter Django
  [settings docs](https://cookiecutter-django.readthedocs.io/en/latest/1-getting-started/settings.html)
  for the full list of supported variables.

> [!CAUTION]
> Never commit real env files — only the `*.example` templates belong in version control.
> Rotate any credential that has ever been exposed.

---

## Deployment

A production Docker Compose stack is provided in `docker-compose.production.yml`: the Django
app (Gunicorn/Uvicorn), Postgres, Redis, Celery worker/beat/flower, the Next.js app, an AWS
CLI backup helper, and a **Traefik** reverse proxy with automatic Let's Encrypt TLS. Build and
run it with your production env files in place:

```bash
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml run --rm django python manage.py migrate
docker compose -f docker-compose.production.yml up -d
```

Production migrations are deliberately a deploy step, not a container startup side effect. The
production `/start` script collects static files and launches Gunicorn; it does not run
`migrate`, which avoids multiple app containers racing to apply schema changes. Create a
superuser separately when needed:

```bash
docker compose -f docker-compose.production.yml run --rm django python manage.py createsuperuser
```

<details>
<summary><b>Database backups (S3)</b></summary>

<br>

Backups are created on the `postgres` container and shipped to S3 by an on-demand `awscli`
maintenance container (behind a Compose `maintenance` profile, so it doesn't start with `up`):

```bash
# Dump the database into the backups volume
docker compose -f docker-compose.production.yml exec postgres backup

# Upload / download the backups folder to / from S3
docker compose -f docker-compose.production.yml run --rm awscli upload
docker compose -f docker-compose.production.yml run --rm awscli download
```

</details>

See the Cookiecutter Django
[deployment guide](https://cookiecutter-django.readthedocs.io/en/latest/3-deployment/deployment-with-docker.html)
for hardening, TLS, backups, and CI/CD details.

### Reverse proxy & TLS (Traefik)

The production stack is fronted by [Traefik](https://traefik.io/), which terminates TLS and
routes all inbound traffic. Its config lives in `backend/compose/production/traefik/`, split
into a **static** config (`traefik.yml`) and a **dynamic** config (`dynamic.yml`).

<details>
<summary><b>Routing, TLS, headers &amp; network isolation</b> — the full breakdown</summary>

<br>

- **Automatic HTTPS.** Traefik obtains and renews Let's Encrypt certificates via the ACME
  HTTP-01 challenge and stores them in the `production_traefik` volume. The registration email
  is baked in at build time from the `TRAEFIK_ACME_EMAIL` build arg (Traefik does not
  interpolate env vars in its static config), so set it per environment:
  ```bash
  export TRAEFIK_ACME_EMAIL=ops@example.com
  docker compose -f docker-compose.production.yml build traefik
  ```
- **HTTP → HTTPS.** Port `:80` redirects to `:443`; TLS is restricted to a modern cipher suite
  (TLS 1.2+).
- **Path-based routing** on the apex host:
  - `/admin` → **Django**, on a dedicated **rate-limited** router (login brute-force
    mitigation). The real admin lives at an obscured `DJANGO_ADMIN_URL`; probing `/admin` (or
    any wrong path) returns Django's error page, which is **brand-neutral and self-contained**
    — no `base.html` chrome, no Bootstrap/CDN, no project name, no exception echo — so it
    doesn't fingerprint the backend as Django and looks generically like the frontend 404.
    (This is cosmetic: `/static/admin` and `/api/docs` still reveal the stack. The neutral
    pages live in `backend/<project>/templates/` — `404.html`, `403.html`, `500.html`. If you
    give the Next.js frontend a custom not-found page, mirror it there too.)
  - `/api`, `/static`, `/media` → **Django**
  - everything else (apex + `www`) → **Next.js** (catch-all)
  - port `:5555` → **Flower** on a dedicated entrypoint
- **Security headers — Traefik is authoritative.** One shared `security-headers` middleware is
  applied to **both** the Django and Next.js routers so responses look the same and don't leak
  which backend served them: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, a referrer
  policy, a `Permissions-Policy`, and **stripping the backend `Server` header**. Because
  Traefik re-stamps these on the way out, **its values win over Django's** for proxied
  (public) traffic. `X-Frame-Options` is `DENY` at **both** layers — Traefik's
  `customFrameOptionsValue` and Django's `X_FRAME_OPTIONS` — so the clickjacking policy is
  identical whether a response is proxied or hit directly; HSTS is Traefik's `stsSeconds` (not
  Django's `SECURE_HSTS_SECONDS`). HSTS in particular belongs at the TLS-terminating edge,
  which is Traefik. Django still emits its own headers as defense-in-depth for any **direct,
  non-proxied** access (e.g. from inside the Docker network), so nothing is lost — but **to
  change what a browser actually receives, edit `dynamic.yml`**; changing the Django settings
  alone won't affect proxied responses.
- **Network isolation.** Traefik lives only on the `web` network; Postgres and Redis live only
  on `backend`. Django and Flower bridge both because they serve HTTP *and* need the data
  stores — so the edge can never reach the databases directly.

Before deploying, update the hostnames in `dynamic.yml` (currently `__DOMAIN__` /
`www.__DOMAIN__`) and the `NEXT_PUBLIC_API_URL` build arg to match your own domain.

</details>

---

## Project structure

```
.
├── backend/                       # Django project (Cookiecutter Django base)
│   ├── config/                    # project glue
│   │   ├── settings/              # base · local · production · test
│   │   ├── urls.py                # root URLConf (admin, allauth, pages, /api)
│   │   ├── api_router.py          # DRF router → API viewsets
│   │   ├── asgi.py                # ASGI app: http → Django, websocket → handler
│   │   ├── websocket.py           # minimal ASGI WebSocket endpoint
│   │   └── celery_app.py          # Celery app definition
│   ├── __PROJECT_SLUG__/          # application code
│   │   ├── users/                 # custom user model + api/ (serializers, views), tasks, adapters
│   │   ├── templates/             # server-rendered pages & allauth
│   │   └── static/                # backend static assets
│   ├── compose/                   # Dockerfiles & entrypoints (local + production)
│   │   └── production/traefik/    # traefik.yml (static) + dynamic.yml (routers/TLS)
│   ├── tests/                     # backend tests
│   ├── pyproject.toml             # dependencies & tool config (uv, ruff, mypy, pytest)
│   ├── uv.lock                    # pinned, hash-verified dependency lockfile (committed)
│   └── manage.py
├── frontend/                      # Next.js app
│   ├── src/app/                   # App Router pages, layout, styles
│   ├── public/                    # static assets
│   ├── compose/                   # Dockerfiles (local + production)
│   ├── pnpm-lock.yaml             # frontend lockfile (committed)
│   └── package.json
├── docker-compose.local.yml       # full local stack
├── docker-compose.production.yml  # prod stack: Traefik, Django, Next.js, Postgres, Redis, Celery, awscli
├── docker-compose.docs.yml        # Sphinx docs server
└── .github/workflows/ci.yml       # CI: lint, type-check, build, tests
```

---

## Contributing

Contributions are welcome!

1. Fork the repository and create a feature branch.
2. Make your changes and ensure linters, type checks, and tests pass.
3. Run `pre-commit` before committing.
4. Open a pull request with a clear description and a test plan.

---

## License

Released under the [MIT License](LICENSE). © 2026 __AUTHOR_NAME__.

---

## Acknowledgements

DjangoNext stands on the shoulders of two excellent project generators:

- **[Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django)** — the backend
  was scaffolded from this project template
  ([BSD-licensed](https://github.com/cookiecutter/cookiecutter-django/blob/master/LICENSE)).
  Thank you to its maintainers and contributors.
- **[create-next-app](https://nextjs.org/docs/app/api-reference/cli/create-next-app)** — the
  frontend was bootstrapped with the official Next.js starter (MIT, © Vercel).
