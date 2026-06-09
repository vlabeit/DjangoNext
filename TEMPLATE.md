# Using This Template

This repo is a **bootstrappable starter template**. It does not run until you bootstrap it.

## Quick start

```bash
git clone <this-repo> my-project
cd my-project
python3 install.py
```

## What install.py does

1. Prompts for project values (or reads them from `--config FILE`).
2. Replaces `__TOKEN__` sentinels across all text files.
3. Renames `backend/__PROJECT_SLUG__/` to `backend/<your-slug>/`.
4. Applies the chosen media backend — the `config/settings/production.py` storage block, plus (for `media=local`) the production nginx media sidecar, or (for `media=aws`) removing the unused `compose/production/nginx/` build context (see **Media backends** below). The `# >>> TEMPLATE:MEDIA … <<<` markers are then stripped so the bootstrapped configs carry no scaffolding.
5. Generates real `.env` files with fresh secrets from the committed `.example` seeds. The real env files stay gitignored, and the `.example` seeds remain as safe templates for future reference.
6. Removes template-only scaffolding: `TEMPLATE.md`, the root `pyproject.toml`, `tests/`, and the README's "Use this template" section.
7. Removes itself and `.template-marker` (unless `--keep-script`).

`install.py` is a standalone script — it requires **Python 3.11+** and no additional packages.
The `backend/pyproject.toml` `requires-python = "==3.14.*"` applies to the Django app only.

## Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview changes; do not modify any file |
| `--config FILE` | Non-interactive; read answers from JSON |
| `--yes` | Skip the confirmation prompt |
| `--keep-script` | Preserve `install.py` and `.template-marker` after run |
| `--force` | Run even if already bootstrapped (tokens consumed) |
| `--start` | After bootstrapping, build & start the stack non-interactively (works with `--yes`/`--config`). Brings up **dev** by default; add `--production` for prod. Skips the TTY-only `createsuperuser` step — create one afterwards with the printed command. |
| `--production`, `--prod` | Target the **production** stack for bring-up (default: dev). Affects both the interactive offer and `--start`. |
| `--destroy` | When bringing up the stack, first reset (destroy) this project's database volume for a fresh start. Same as `"destroy": true` in the config JSON. **Destroys** the chosen env's DB data. |

Note: `--keep-script` preserves **both** `install.py` **and** `.template-marker`. A re-run after `--keep-script` requires `--force` because tokens have been consumed.

Bring-up: at a terminal (and without `--yes`) the run *offers* to build & start the stack — even when answers come from `--config`. `--yes` and piped/CI runs stay silent. To bring the stack up without prompts, either pass `--start` (env **dev** unless `--production`) **or** set `"start"` in the config JSON. Add `--destroy` / `"destroy": true` to reset the database first.

## Config JSON schema

```json
{
  "project_name":        "AcmeCorp",
  "project_slug":        "acmecorp",
  "domain":              "acmecorp.example.com",
  "author_name":         "Jane Doe",
  "author_email":        "jane@acmecorp.example.com",
  "project_description": "A tagline for AcmeCorp.",
  "timezone":            "UTC",
  "media":               "local",
  "start":               "dev",
  "destroy":             false
}
```

Required: `project_name`, `project_slug`, `domain`, `author_email`, `media`.
Optional: `author_name`, `project_description`, `timezone` (default `UTC`).

`author_email` is required because it feeds the Let's Encrypt ACME registration email
(`TRAEFIK_ACME_EMAIL`) baked into the production Traefik image, as well as Django `ADMINS` and
`pyproject.toml` — an empty value silently blocks certificate issuance on the first prod deploy.
Bring-up (optional, non-interactive — applied after bootstrap):

- `"start"` — `false` (default) skips bring-up; `"dev"` (or `true`) builds & starts the dev stack; `"prod"` the production stack. Equivalent to `--start` (+`--production`).
- `"destroy"` — `true` resets (destroys) this project's database volume for the chosen env *before* starting, so a re-run avoids the `password authentication failed` trap. Default `false`. Equivalent to `--destroy`. **Destroys the existing DB data** for that env (Redis and Traefik certs are left intact).

CLI flags override the JSON (e.g. `--production` forces prod; `--destroy` forces the reset).

## Media backends

User-uploaded media is handled differently per `media` choice (static files are always served by WhiteNoise from Django):

- **`aws`** — uploads go to S3 via `django-storages`; no media server is needed. `DJANGO_AWS_*` keys are present-but-blank in `.envs/.production/.django` for you to fill.
- **`local`** — uploads use Django's `FileSystemStorage` on a shared `production_django_media` volume. Because WhiteNoise does **not** serve user media, bootstrap wires an **nginx sidecar** for production:
  - an `nginx` service + `production_django_media` volume in `docker-compose.production.yml`,
  - the volume mounted on `django` (and, via the `&django` anchor, `celeryworker`/`celerybeat`/`flower`),
  - a Traefik router `Host(...) && PathPrefix(/media)` → nginx at priority `200` (beats Django's `100`), backed by `http://nginx:80`.

  Pick `local` for single-host deploys without S3. In local **dev** (`docker-compose.local.yml`, `DEBUG=True`) Django serves media directly, so the sidecar is production-only.

## Token reference

| Token | Replaces | Example |
|-------|----------|---------|
| `__PROJECT_SLUG__` | Python package name, Docker image/volume names, `pyproject.toml` name | `acmecorp` |
| `__PROJECT_NAME__` | Display name in UI, docs, email subjects | `AcmeCorp` |
| `__DOMAIN__` | Production hostname in configs, Traefik rules, env defaults | `acmecorp.example.com` |
| `__AUTHOR_NAME__` | Author credit in docs, meta tags, PO headers | `Jane Doe` |
| `__AUTHOR_EMAIL__` | Author email in pyproject.toml, ADMINS, PO headers, Traefik ACME default | `jane@acmecorp.example.com` |
| `__PROJECT_DESCRIPTION__` | Tagline in README, meta description, pyproject.toml | `A tagline for AcmeCorp.` |
| `__TIMEZONE__` | `TIME_ZONE` in Django settings | `America/New_York` |

Note: `traefik.yml`'s `__ACME_EMAIL__` is a **Docker build-time** placeholder substituted at image build
via the `TRAEFIK_ACME_EMAIL` build arg — it is **not** an `install.py` token. The `__AUTHOR_EMAIL__`
token covers the Let's Encrypt fallback default in `docker-compose.production.yml`.

## Post-install checklist

After running `python3 install.py`, set these secrets manually:

```
[ ] MAILGUN_API_KEY / MAILGUN_DOMAIN        -> backend/.envs/.production/.django
[ ] SENTRY_DSN                               -> backend/.envs/.production/.django and
                                               frontend/.envs/.production/.next
[ ] DJANGO_SERVER_EMAIL                     -> backend/.envs/.production/.django
[ ] DJANGO_AWS_ACCESS_KEY_ID / SECRET / BUCKET  -> only if you chose media=aws
```

Additional steps:

```
[ ] Update TRAEFIK_ACME_EMAIL in your CI/CD or docker build args to your email
```
