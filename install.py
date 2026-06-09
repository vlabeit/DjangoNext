#!/usr/bin/env python3
"""install.py — Repo template bootstrapper.

Dependency-free. Requires Python 3.11+.

Usage:
    python3 install.py                        # interactive
    python3 install.py --config answers.json  # non-interactive
    python3 install.py --dry-run              # preview only
    python3 install.py --keep-script          # do not self-delete
    python3 install.py --force                # run even if already bootstrapped
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import secrets
import shutil
import stat
import string
import subprocess
import sys
from pathlib import Path
from zoneinfo import available_timezones

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKER_START = "# >>> TEMPLATE:MEDIA <<<"
MARKER_END = "# >>> TEMPLATE:MEDIA:END <<<"

TEMPLATE_MARKER_FILENAME = ".template-marker"

# Files/dirs never scanned or modified by the token-replace pass.
# Directory names match any path COMPONENT (not just top-level).
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "staticfiles",
        "__pycache__",
    }
)
# Exact filenames ignored regardless of location.
# This script, its test file, and TEMPLATE.md all contain __TOKEN__ literals as
# data/docs — the token pass must not rewrite them or it would corrupt itself.
# The script itself is skipped by its real filename via should_skip_path's
# __file__ check (not listed here), so a future rename never desyncs the guard.
# NOTE: uv.lock is deliberately NOT skipped. It carries the project's own package
# name as `__PROJECT_SLUG__`, which must track pyproject.toml so `uv sync --locked`
# succeeds after bootstrap. Sentinel tokens never collide with lock hashes/URLs.
# Other lockfiles (pnpm/npm/yarn/cargo) don't encode the renamable project name.
SKIP_FILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "test_install.py",
        "TEMPLATE.md",
    }
)

# Canonical AWS media block written into the TEMPLATE:MEDIA region of
# config/settings/production.py when media=aws.
AWS_MEDIA_BLOCK = '''\
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_ACCESS_KEY_ID = env("DJANGO_AWS_ACCESS_KEY_ID")
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_SECRET_ACCESS_KEY = env("DJANGO_AWS_SECRET_ACCESS_KEY")
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_STORAGE_BUCKET_NAME = env("DJANGO_AWS_STORAGE_BUCKET_NAME")
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_QUERYSTRING_AUTH = False
# DO NOT change these unless you know what you're doing.
_AWS_EXPIRY = 60 * 60 * 24 * 7
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": f"max-age={_AWS_EXPIRY}, s-maxage={_AWS_EXPIRY}, must-revalidate",
}
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_S3_MAX_MEMORY_SIZE = env.int(
    "DJANGO_AWS_S3_MAX_MEMORY_SIZE",
    default=100_000_000,  # 100MB
)
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_S3_REGION_NAME = env("DJANGO_AWS_S3_REGION_NAME", default=None)
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#cloudfront
AWS_S3_CUSTOM_DOMAIN = env("DJANGO_AWS_S3_CUSTOM_DOMAIN", default=None)
aws_s3_domain = AWS_S3_CUSTOM_DOMAIN or f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
# STATIC & MEDIA
# ------------------------
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "location": "media",
            "file_overwrite": False,
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = f"https://{aws_s3_domain}/media/"'''

LOCAL_MEDIA_BLOCK = '''\
# STATIC & MEDIA
# ------------------------
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "/media/"'''


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_slug(value: str) -> str | None:
    """Return an error message string, or None if valid."""
    if not value:
        return "Project slug must not be empty."
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        return (
            f"Invalid slug {value!r}. Must match ^[a-z][a-z0-9_]*$ "
            "(lowercase letters, digits, underscores; start with a letter)."
        )
    if keyword.iskeyword(value):
        return (
            f"Slug {value!r} is a Python keyword and cannot be used as a package name."
        )
    return None


def validate_domain(value: str) -> str | None:
    if not value:
        return "Domain must not be empty."
    # Reject obvious non-hostnames
    if "://" in value or "/" in value:
        return f"Domain {value!r} must be a bare hostname (no scheme or path)."
    hostname_re = re.compile(
        r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)"
        r"+[a-zA-Z]{2,}$"
    )
    if not hostname_re.fullmatch(value):
        return (
            f"Domain {value!r} does not look like a valid hostname "
            "(e.g. example.com or sub.example.co.uk)."
        )
    return None


def validate_email(value: str) -> str | None:
    """Validate email FORMAT only; an empty string passes this check.

    The non-empty *requirement* for author_email is enforced in
    _validate_answers — it feeds Let's Encrypt ACME (TRAEFIK_ACME_EMAIL), Django
    ADMINS/MANAGERS, and pyproject.toml, so it must be provided.
    """
    if not value:
        return None
    email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    if not email_re.fullmatch(value):
        return f"Email {value!r} does not look valid."
    return None


def validate_timezone(value: str) -> str | None:
    """Empty string means use the default (UTC); any non-empty value must be valid."""
    if not value:
        return None
    if value not in available_timezones():
        return (
            f"Timezone {value!r} is not a recognised IANA timezone. "
            "Try e.g. 'America/New_York' or 'Europe/London'."
        )
    return None


# ---------------------------------------------------------------------------
# Credential / secret generators
# ---------------------------------------------------------------------------


def generate_secret_key() -> str:
    """Generate a Django SECRET_KEY: URL-safe, ≥50 chars."""
    return secrets.token_urlsafe(64)


def generate_admin_url() -> str:
    """Generate an obscured admin URL under the 'admin/' prefix, ending in '/'.

    The 'admin/' prefix is required in production: Traefik routes only
    PathPrefix(`/admin`) (plus /api, /static, /media) to Django, so a fully
    random path would fall through to the Next.js catch-all and 404. The random
    suffix is the actual protection — bare /admin/ returns a Django 404.

    The suffix matches cookiecutter-django's DJANGO_ADMIN_URL scheme: 32 random
    alphanumeric characters (digits + ASCII letters, no punctuation), drawn from
    the `secrets` CSPRNG.
    """
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(32))
    return "admin/" + suffix + "/"


def generate_password(nbytes: int = 32) -> str:
    """Generate a URL-safe password of ≥24 characters."""
    return secrets.token_urlsafe(nbytes)


def generate_short_id(nbytes: int = 8) -> str:
    """Generate a short hex identifier."""
    return secrets.token_hex(nbytes)


# ---------------------------------------------------------------------------
# Token replacement engine
# ---------------------------------------------------------------------------


def replace_tokens(text: str, token_map: dict[str, str]) -> str:
    """Substitute every token in ``token_map`` in a SINGLE pass.

    A single regex pass replaces each token exactly once, so a value that itself
    contains another token literal — e.g. a free-text project name of
    ``__PROJECT_SLUG__`` — is emitted verbatim and never re-expanded by a later
    substitution. The alternation is built longest-key-first so it can never
    match a prefix of a longer token; order is otherwise irrelevant, because
    single-pass replacement removes the multi-pass re-expansion hazard entirely.
    Empty-string keys are ignored (they would otherwise match at every position).
    """
    keys = sorted((k for k in token_map if k), key=len, reverse=True)
    if not keys:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    return pattern.sub(lambda m: token_map[m.group(0)], text)


# ---------------------------------------------------------------------------
# Ignore-list / binary detection
# ---------------------------------------------------------------------------


def _contains_null_byte(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return False


def should_skip_path(path: Path, repo_root: Path) -> bool:
    """Return True if this path should be excluded from the token-replace pass."""
    # Skip any path whose components include a skip-dir name.
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return False

    for part in rel.parts[:-1]:  # directory components only
        if part in SKIP_DIRS:
            return True

    filename = path.name
    # Skip the explicit skip-files and this bootstrapper script itself. The script
    # is matched by its real filename (Path(__file__).name) rather than a hardcoded
    # literal, so renaming the script never leaves it exposed to the token pass.
    if filename in SKIP_FILES or filename == Path(__file__).name:
        return True

    # Binary sniff (after the explicit skip-file check so we don't read lockfiles).
    if path.is_file() and _contains_null_byte(path):
        return True

    return False


# ---------------------------------------------------------------------------
# Media-block writer
# ---------------------------------------------------------------------------


def write_marked_region(path: Path, tag: str, body: str) -> None:
    """Replace the content between '# >>> {tag} <<<' and '# >>> {tag}:END <<<'.

    The start marker's leading indentation is preserved on both markers; ``body``
    supplies its own indentation. Pass body='' to clear the region. Idempotent.
    Raises ValueError if the markers are not present.
    """
    start = f"# >>> {tag} <<<"
    end = f"# >>> {tag}:END <<<"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?P<indent>[ \t]*)" + re.escape(start) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    m = pattern.search(text)
    if m is None:
        raise ValueError(f"Markers for {tag!r} not found in {path}.")
    indent = m.group("indent")
    region = (
        f"{indent}{start}\n{body}\n{indent}{end}"
        if body
        else f"{indent}{start}\n{indent}{end}"
    )
    path.write_text(text[: m.start()] + region + text[m.end() :], encoding="utf-8")


def write_media_block(production_py_path: Path, variant: str) -> None:
    """Rewrite the TEMPLATE:MEDIA region in production.py with the chosen variant.

    variant must be 'aws' or 'local'. The markers are preserved; only the content
    between them changes. Idempotent.
    """
    if variant not in ("aws", "local"):
        raise ValueError(f"variant must be 'aws' or 'local', got {variant!r}")
    block_body = AWS_MEDIA_BLOCK if variant == "aws" else LOCAL_MEDIA_BLOCK
    write_marked_region(production_py_path, "TEMPLATE:MEDIA", block_body)


def _is_media_start_marker(line: str) -> bool:
    s = line.strip()
    return (
        s.startswith("# >>> TEMPLATE:MEDIA") and s.endswith("<<<") and ":END" not in s
    )


def _is_media_end_marker(line: str) -> bool:
    s = line.strip()
    return s.startswith("# >>> TEMPLATE:MEDIA") and s.endswith(":END <<<")


def strip_template_markers(path: Path) -> None:
    """Remove every '# >>> TEMPLATE:MEDIA … <<<' marker pair from a file.

    Markers are kept in place during media wiring (so the regions stay locatable
    and the writer is idempotent), then removed here as the final step so the
    bootstrapped repo carries no template scaffolding.

    - A region whose body is empty/whitespace-only (media=aws) is dropped
      entirely, consuming one immediately-preceding blank line so no double or
      trailing blank is left behind.
    - A region with real content (the filled production.py block, or any
      media=local body) keeps its content; only the two marker lines are removed.

    No-op if the file has no markers. Tolerant of missing files.
    """
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _is_media_start_marker(line):
            j = i + 1
            while j < n and not _is_media_end_marker(lines[j]):
                j += 1
            if j >= n:
                raise ValueError(
                    f"Unclosed TEMPLATE:MEDIA marker in {path}: the start marker "
                    f"on line {i + 1} has no matching ':END' marker."
                )
            body = lines[i + 1 : j]
            if all(b.strip() == "" for b in body):
                # Empty region (aws): drop markers + body, collapse a preceding blank.
                if out and out[-1].strip() == "":
                    out.pop()
            else:
                # Filled region: keep body, drop the two marker lines.
                out.extend(body)
            i = j + 1  # skip past the end marker
            continue
        out.append(line)
        i += 1
    path.write_text("".join(out), encoding="utf-8")


def strip_marked_region(path: Path, name: str) -> None:
    """Delete every '# >>> {name} … <<<' region — markers AND body — from a file.

    Unlike strip_template_markers (which keeps a filled body and only drops the
    two marker lines), this removes the whole block, consuming one immediately
    preceding blank line so no gap is left behind. Used to drop template-only CI
    steps that a bootstrapped project has no use for (its CI runs the checks
    directly, with no template left to bootstrap).

    No-op if the file or the markers are absent. Raises on an unclosed marker.
    """
    if not path.exists():
        return

    def _is_start(line: str) -> bool:
        s = line.strip()
        return s.startswith(f"# >>> {name}") and s.endswith("<<<") and ":END" not in s

    def _is_end(line: str) -> bool:
        s = line.strip()
        return s.startswith(f"# >>> {name}") and s.endswith(":END <<<")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if _is_start(lines[i]):
            j = i + 1
            while j < n and not _is_end(lines[j]):
                j += 1
            if j >= n:
                raise ValueError(
                    f"Unclosed {name} marker in {path}: the start marker on "
                    f"line {i + 1} has no matching ':END' marker."
                )
            # Consume one immediately-preceding blank so two surrounding blanks
            # (before and after the region) collapse to a single separator.
            if out and out[-1].strip() == "":
                out.pop()
            i = j + 1  # skip past the end marker
            continue
        out.append(lines[i])
        i += 1
    path.write_text("".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# Media-serving infrastructure (production compose + Traefik)
# ---------------------------------------------------------------------------
# media=local: user uploads are served by an nginx sidecar reading the
#   production_django_media volume (Django + celeryworker write to it).
# media=aws: every region is cleared (S3 serves media directly).
# The committed template ships these regions empty; bootstrap fills them.

_COMPOSE_PROD = "docker-compose.production.yml"
_TRAEFIK_DYNAMIC = "backend/compose/production/traefik/dynamic.yml"
_PROD_DJANGO_DOCKERFILE = "backend/compose/production/django/Dockerfile"
_NGINX_DIR = "backend/compose/production/nginx"

# Files whose TEMPLATE:MEDIA marker pairs are stripped after media wiring.
_MEDIA_MARKER_FILES = (
    "backend/config/settings/production.py",
    _COMPOSE_PROD,
    _TRAEFIK_DYNAMIC,
    _PROD_DJANGO_DOCKERFILE,
)

# Each *_BODY is the LOCAL-mode content for its marker region (descriptive comment
# included). For media=aws the region is emptied and the markers are stripped, so
# these comments never reach an aws build. Bodies supply their own indentation.

_NGINX_SERVICE_BODY = """\
  # nginx media sidecar — serves /media from the shared production_django_media volume.
  nginx:
    build:
      context: ./backend/
      dockerfile: ./compose/production/nginx/Dockerfile
    image: {slug}_production_nginx
    depends_on:
      django:
        condition: service_healthy
    volumes:
      - production_django_media:/usr/share/nginx/media:ro
    restart: unless-stopped
    networks: [web]"""

_NGINX_ROUTER_BODY = """\
    # /media → nginx sidecar (priority 200 beats django's 100).
    nginx-media-secure-router:
      rule: '(Host(`{domain}`) || Host(`www.{domain}`)) && PathPrefix(`/media`)'
      priority: 200
      entryPoints:
        - web-secure
      service: nginx
      tls:
        certResolver: letsencrypt
        options: modern"""

_NGINX_SERVICE_BACKEND_BODY = """\
    # nginx media backend (serves /media).
    nginx:
      loadBalancer:
        servers:
          - url: http://nginx:80"""

_DOCKERFILE_MEDIA_BODY = """\
# Ensure MEDIA_ROOT exists and is owned by django BEFORE switching users, so the
# local-media named volume mounted there is writable by the non-root app user.
RUN mkdir -p ${{APP_HOME}}/{slug}/media \\
  && chown -R django:django ${{APP_HOME}}/{slug}/media"""


def _media_infra_regions(slug: str, domain: str) -> list[tuple[str, str, str]]:
    """Return (relative_path, marker_tag, local_body) for each media region."""
    return [
        (_COMPOSE_PROD, "TEMPLATE:MEDIA:VOLUME", "  production_django_media: {}"),
        (
            _COMPOSE_PROD,
            "TEMPLATE:MEDIA:MOUNT",
            f"    volumes:\n      - production_django_media:/app/{slug}/media",
        ),
        (_COMPOSE_PROD, "TEMPLATE:MEDIA:NGINX", _NGINX_SERVICE_BODY.format(slug=slug)),
        (
            _TRAEFIK_DYNAMIC,
            "TEMPLATE:MEDIA:ROUTER",
            _NGINX_ROUTER_BODY.format(domain=domain),
        ),
        (_TRAEFIK_DYNAMIC, "TEMPLATE:MEDIA:SERVICE", _NGINX_SERVICE_BACKEND_BODY),
        (
            _PROD_DJANGO_DOCKERFILE,
            "TEMPLATE:MEDIA:DOCKERFILE",
            _DOCKERFILE_MEDIA_BODY.format(slug=slug),
        ),
    ]


def apply_media_infrastructure(
    repo_root: Path, media: str, slug: str, domain: str
) -> None:
    """Wire (media=local) or clear (media=aws) the production media-serving regions.

    Tolerant of absent files/markers so it never blocks a bootstrap run: regions
    that exist are filled for 'local' and emptied for 'aws'. The nginx build
    context (backend/compose/production/nginx/) is removed entirely for media=aws,
    where S3 serves uploads and no sidecar is built.
    """
    for rel, tag, local_body in _media_infra_regions(slug, domain):
        path = repo_root / rel
        if not path.exists():
            continue
        try:
            write_marked_region(path, tag, local_body if media == "local" else "")
        except ValueError:
            continue  # markers absent in this file — nothing to wire

    if media == "aws":
        nginx_dir = repo_root / _NGINX_DIR
        if nginx_dir.is_dir():
            shutil.rmtree(nginx_dir)


# ---------------------------------------------------------------------------
# Env-file generation
# ---------------------------------------------------------------------------

# Keys generated only in production .django env (absent from local by design).
_PRODUCTION_DJANGO_ONLY_KEYS = frozenset(
    {
        "DJANGO_SECRET_KEY",
        "DJANGO_ADMIN_URL",
    }
)

# Flower creds are generated ONLY for production .django; local preserves debug/debug.
_PRODUCTION_DJANGO_FLOWER_KEYS = frozenset(
    {
        "CELERY_FLOWER_USER",
        "CELERY_FLOWER_PASSWORD",
    }
)

# Keys that must stay blank (never auto-generate).
_BLANK_KEYS = frozenset(
    {
        "MAILGUN_API_KEY",
        "MAILGUN_DOMAIN",
        "DJANGO_SERVER_EMAIL",
        "SENTRY_DSN",
        "DJANGO_AWS_ACCESS_KEY_ID",
        "DJANGO_AWS_SECRET_ACCESS_KEY",
        "DJANGO_AWS_STORAGE_BUCKET_NAME",
    }
)

# Production-only env keys whose value is derived from the project domain.
# Committed *.example seeds keep generic example.com placeholders; the real
# generated PRODUCTION env files get the domain formatted per this table. This
# table is the single source of truth for the seed↔installer link — wire up a
# new domain-bearing key by adding it here, not by editing code below.
_DOMAIN_KEY_FORMATS = {
    "DJANGO_ALLOWED_HOSTS": ".{domain}",
    "PLAYWRIGHT_TEST_BASE_URL": "https://{domain}",
}


def _generate_value_for_key(key: str) -> str | None:
    """Return a generated secret for key, or None if the key must stay blank."""
    if key == "DJANGO_SECRET_KEY":
        return generate_secret_key()
    if key == "DJANGO_ADMIN_URL":
        return generate_admin_url()
    if key == "POSTGRES_PASSWORD":
        return generate_password()
    if key == "CELERY_FLOWER_USER":
        return generate_short_id()
    if key == "CELERY_FLOWER_PASSWORD":
        return generate_password(24)
    return None  # key stays blank


def _domain_value_for_key(key: str, domain: str) -> str | None:
    """Return the real-domain value for a domain-bearing env key, or None.

    Driven by _DOMAIN_KEY_FORMATS so the seed↔installer mapping lives in one
    explicit table rather than being hard-coded per key. Committed *.example
    seeds keep generic example.com placeholders; the real domain is injected
    into the generated production env files only.
    """
    if not domain:
        return None
    fmt = _DOMAIN_KEY_FORMATS.get(key)
    return fmt.format(domain=domain) if fmt is not None else None


def _is_production_env(env_path: Path) -> bool:
    return ".production" in env_path.parts


def _is_local_env(env_path: Path) -> bool:
    return ".local" in env_path.parts


def _is_django_env(env_path: Path) -> bool:
    return env_path.name in (".django", "django")


def _strip_aws_lines(lines: list[str]) -> list[str]:
    """Drop DJANGO_AWS_* settings and their django-storages comment lines (media=local)."""
    filtered = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("DJANGO_AWS_") or (
            stripped.startswith("#")
            and "AWS" in stripped
            and "django-storages" in stripped
        ):
            continue
        filtered.append(line)
    return filtered


def _fill_secrets_in_lines(
    lines: list[str], is_prod: bool, is_local: bool, is_django: bool, domain: str = ""
) -> list[str]:
    """Fill each KEY=VALUE line with a generated secret per the by-key rules."""
    result_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            result_lines.append(line)
            continue
        key = stripped.partition("=")[0].strip()
        # Only production env files carry the real domain; local files keep their
        # compose-network seed values (e.g. http://next:3000).
        domain_value = _domain_value_for_key(key, domain) if is_prod else None
        if domain_value is not None:
            result_lines.append(f"{key}={domain_value}\n")  # real domain → real prod file
        elif key in _BLANK_KEYS:
            result_lines.append(f"{key}=\n")  # externally-provided: stays blank
        elif is_local and is_django and key in _PRODUCTION_DJANGO_FLOWER_KEYS:
            result_lines.append(line)  # local Flower creds preserved (debug/debug)
        elif key in _PRODUCTION_DJANGO_ONLY_KEYS and not is_prod:
            result_lines.append(line)  # production-only key absent from local — copy
        elif key == "POSTGRES_USER" and is_prod:
            result_lines.append(f"{key}={generate_short_id()}\n")
        else:
            generated = _generate_value_for_key(key)
            result_lines.append(
                f"{key}={generated}\n" if generated is not None else line
            )
    return result_lines


def _generate_env_file(
    example_path: Path,
    media: str,
    domain: str = "",
) -> None:
    """Create a real env file from an .example sibling, filling secrets by key.

    Rules (all from the verified spec):
    - DJANGO_SECRET_KEY, DJANGO_ADMIN_URL: production .django only.
    - CELERY_FLOWER_USER, CELERY_FLOWER_PASSWORD:
        - local .django: preserve 'debug/debug' from example as-is.
        - production .django: generate.
    - POSTGRES_PASSWORD: randomized wherever the key appears (local + production).
    - POSTGRES_USER: production generates a short hex id; local preserves the seed
      value (the readable project-slug identifier).
    - AWS keys (DJANGO_AWS_*): present-but-blank on 'aws'; skip entire AWS section on 'local'.
    - Keys that must stay blank: MAILGUN_API_KEY, MAILGUN_DOMAIN, SENTRY_DSN, etc.
    - Secrets are NOT echoed to stdout.
    """
    dest = example_path.with_suffix("")
    is_prod = _is_production_env(example_path)
    is_local = _is_local_env(example_path)
    is_django = _is_django_env(dest)

    lines = example_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if is_prod and is_django and media == "local":
        lines = _strip_aws_lines(lines)
    result_lines = _fill_secrets_in_lines(lines, is_prod, is_local, is_django, domain)

    dest.write_text("".join(result_lines), encoding="utf-8")
    dest.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600

    # The .example seed is a committed, gitignore-safe stand-in. Keep it after
    # generating the real sibling so a fresh clone still has env templates to copy
    # from. The .gitignore tracks *.example and ignores the real, secret-filled
    # files, so no secrets are ever committed.


def generate_env_files(repo_root: Path, media: str, domain: str = "") -> None:
    """Find all .example env files and create real siblings."""
    for env_root in (
        repo_root / "backend" / ".envs",
        repo_root / "frontend" / ".envs",
    ):
        if not env_root.exists():
            continue
        for example in env_root.rglob("*"):
            if example.is_file() and example.name.endswith(".example"):
                _generate_env_file(example, media, domain)


# ---------------------------------------------------------------------------
# Token-replace file-walk engine
# ---------------------------------------------------------------------------


def _apply_tokens_to_file(path: Path, token_map: dict[str, str]) -> bool:
    """Replace tokens in a single file. Returns True if the file was modified."""
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False

    updated = replace_tokens(original, token_map)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def token_replace_pass(
    repo_root: Path,
    token_map: dict[str, str],
    dry_run: bool = False,
) -> list[Path]:
    """Walk all non-excluded text files and substitute tokens.

    IMPORTANT: This pass processes file CONTENTS while the directory is still
    named backend/__PROJECT_SLUG__/ — the directory rename (step 5) runs AFTER.
    This ensures import path strings like 'import __PROJECT_SLUG__.users' are
    replaced before the filesystem rename occurs.

    Returns list of modified paths.
    """
    modified = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if should_skip_path(path, repo_root):
            continue
        if dry_run:
            # Peek to see if modification would occur.
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            updated = replace_tokens(text, token_map)
            if updated != text:
                modified.append(path)
        else:
            if _apply_tokens_to_file(path, token_map):
                modified.append(path)
    return modified


# ---------------------------------------------------------------------------
# Package directory rename
# ---------------------------------------------------------------------------


def rename_package_dir(repo_root: Path, slug: str) -> Path:
    """Rename backend/__PROJECT_SLUG__/ to backend/<slug>/.

    Must be called AFTER token_replace_pass() so text substitutions are complete.
    Returns the new directory path.
    """
    old = repo_root / "backend" / "__PROJECT_SLUG__"
    new = repo_root / "backend" / slug
    if not old.exists():
        # Already renamed (idempotent).
        if new.exists():
            return new
        raise FileNotFoundError(
            f"Expected package dir not found: {old}. "
            "Has the directory already been renamed or the template not prepared?"
        )
    shutil.move(str(old), str(new))
    return new


# ---------------------------------------------------------------------------
# Template-scaffolding removal
# ---------------------------------------------------------------------------

# Files/dirs that exist only to develop and document the TEMPLATE itself. They
# must not survive into a bootstrapped project. (This script and
# .template-marker are handled separately by self_delete so --keep-script can
# preserve them.) The trailing entries are dev-tool caches that the template's
# own test harness leaves behind if its tests were run before bootstrapping.
_TEMPLATE_SCAFFOLDING = (
    "TEMPLATE.md",
    "pyproject.toml",
    "tests",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
)

# The README carries a "Use this template" section between these HTML-comment
# markers; it is meaningless once bootstrapped, so the whole block is removed.
_README_DOC_START = "<!-- TEMPLATE:DOC:START -->"
_README_DOC_END = "<!-- TEMPLATE:DOC:END -->"


def strip_readme_doc_section(readme_path: Path) -> None:
    """Remove the README's template-usage section (and the markers themselves).

    Removes from the start marker through the blank line that follows the end
    marker, leaving a single blank line between the description and the body.
    No-op if the markers are absent or the file does not exist.
    """
    if not readme_path.exists():
        return
    text = readme_path.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(_README_DOC_START) + r"\n.*?" + re.escape(_README_DOC_END) + r"\n\n?",
        re.DOTALL,
    )
    new_text = pattern.sub("", text, count=1)
    if new_text != text:
        readme_path.write_text(new_text, encoding="utf-8")


def remove_template_scaffolding(repo_root: Path) -> None:
    """Delete template-only dev files and the README's template-usage section."""
    for name in _TEMPLATE_SCAFFOLDING:
        p = repo_root / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    strip_readme_doc_section(repo_root / "README.md")


# ---------------------------------------------------------------------------
# Self-delete
# ---------------------------------------------------------------------------


def self_delete(repo_root: Path) -> None:
    """Remove this script and .template-marker from repo_root.

    The script's own filename is read from __file__ so a rename of the script
    never leaves a stale copy behind in the bootstrapped project.
    """
    for name in (Path(__file__).name, TEMPLATE_MARKER_FILENAME):
        p = repo_root / name
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------------------
# Stack bring-up (optional, interactive post-install)
# ---------------------------------------------------------------------------
#
# After a successful bootstrap, offer to build and start the running stack for
# the user's chosen environment. The steps mirror the README's documented
# commands:  build -> uv lock -> migrate -> createsuperuser -> up -d.
#
# It is interactive-only: skipped entirely in non-interactive runs (createsuperuser
# needs a TTY) and a no-op when Docker is not installed. The install is meant to
# run once, so this replaces the old volume-pruning housekeeping.

# Compose file per environment.
_COMPOSE_FILES = {
    "dev": "docker-compose.local.yml",
    "prod": "docker-compose.production.yml",
}

# Dev service URLs to surface after a detached `up` (prod sits behind the domain).
_DEV_SERVICE_URLS = (
    ("Frontend (Next.js)", "http://localhost:3000"),
    ("Backend (Django)", "http://localhost:8000"),
    ("API docs (Swagger)", "http://localhost:8000/api/docs/"),
    ("Django admin", "http://localhost:8000/admin/"),
    ("Flower (Celery)", "http://localhost:5555"),
)


def _docker_available() -> bool:
    """True if the docker CLI is on PATH."""
    return shutil.which("docker") is not None


def _list_docker_volumes() -> list[str]:
    """All docker volume names; [] if docker is missing or the daemon errors."""
    try:
        proc = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def _remove_docker_volumes(names: list[str]) -> None:
    """Delete the named docker volumes (best-effort; errors are non-fatal)."""
    if not names:
        return
    try:
        subprocess.run(["docker", "volume", "rm", *names], check=False)
    except OSError:
        pass


def _compose_project_name(repo_root: Path) -> str:
    """Docker Compose's default project name for repo_root (its dir basename).

    Compose lowercases the directory name and keeps only [a-z0-9_-]; we mirror
    that so we can find the volumes it would create. Empty if undeterminable.
    """
    name = re.sub(r"[^a-z0-9_-]", "", repo_root.name.lower())
    return name.lstrip("_-")


def _stale_postgres_volumes(env: str, repo_root: Path) -> list[str]:
    """Existing postgres data/backups volumes for this project's chosen scope.

    At post-install bring-up the DB credentials were just generated, so any
    pre-existing postgres volume holds *different* credentials — Postgres skips
    initialization and rejects them ('password authentication failed'). Matches
    both naming schemes:
      prod: <project>_production_postgres_data[_backups]
      dev : <project>_<slug>_local_postgres_data[_backups]
    """
    project = _compose_project_name(repo_root)
    if not project:
        return []
    needle = f"_{'production' if env == 'prod' else 'local'}_postgres_data"
    return [
        v for v in _list_docker_volumes() if v.startswith(project + "_") and needle in v
    ]


def _bring_up_steps(
    env: str, compose_file: str, *, include_superuser: bool = True
) -> list[tuple[str, list[str], bool]]:
    """Ordered (label, argv, fatal) steps to build and start the stack.

    fatal=True aborts the sequence on a non-zero exit. build/migrate/up are
    fatal (no point continuing without them); lock and createsuperuser are not
    — the shipped lockfile is already valid, and a superuser can be created
    later (the user may also Ctrl-C the interactive createsuperuser prompt).

    'lock' (uv lock) is DEV-ONLY: the production runtime image does not ship uv,
    and its lockfile is baked in at build time, so running it there fails with
    'uv: not found' and would be pointless anyway.

    include_superuser=False drops the createsuperuser step (it needs a TTY) for
    the non-interactive `--start` path; create one later with:
      docker compose -f <compose_file> run --rm django python manage.py createsuperuser
    """
    base = ["docker", "compose", "-f", compose_file]
    django = base + ["run", "--rm", "django"]
    steps: list[tuple[str, list[str], bool]] = [
        ("build", base + ["build"], True),
    ]
    if env == "dev":
        steps.append(("lock", django + ["uv", "lock"], False))
    steps.append(("migrate", django + ["python", "manage.py", "migrate"], True))
    if include_superuser:
        steps.append(
            (
                "createsuperuser",
                django + ["python", "manage.py", "createsuperuser"],
                False,
            )
        )
    steps.append(("up", base + ["up", "-d"], True))
    return steps


def _run_compose_step(argv: list[str], cwd: Path) -> int:
    """Run one compose command, inheriting the terminal; return its exit code.

    Inheriting stdio lets build logs stream and keeps createsuperuser interactive.
    A missing binary or OS error is reported as a non-zero code rather than raising.
    """
    try:
        return subprocess.run(argv, cwd=str(cwd), check=False).returncode
    except OSError:
        return 1


def _read_admin_url(repo_root: Path) -> str:
    """Best-effort read of DJANGO_ADMIN_URL from the generated production env.

    Returns the obscured admin path (e.g. 'admin/abc123/') or '' if the file or
    key is missing — so the printer can still show the rest of the URLs.
    """
    env_file = repo_root / "backend" / ".envs" / ".production" / ".django"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DJANGO_ADMIN_URL="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _print_running_urls(env: str, repo_root: Path, domain: str = "") -> None:
    """Print where the just-started (detached) stack can be reached."""
    if env == "dev":
        print("\n  Stack is starting (detached). Service URLs:")
        for label, url in _DEV_SERVICE_URLS:
            print(f"    {label}: {url}")
        print(
            "\n  Tail logs with: docker compose -f docker-compose.local.yml logs -f"
        )
        return

    base = f"https://{domain}" if domain else "https://<your-domain>"
    admin_url = _read_admin_url(repo_root)
    print("\n  Production stack is starting (detached) behind Traefik. URLs:")
    print(f"    Site (Next.js):     {base}")
    print(f"    API docs (Swagger): {base}/api/docs/   (admin login required)")
    if admin_url:
        print(f"    Django admin:       {base}/{admin_url}")
    print(f"    Flower (Celery):    {base}:5555")
    print("    (URLs need DNS pointing here and an issued Let's Encrypt cert.)")
    print(
        "\n  Tail logs with: docker compose -f docker-compose.production.yml logs -f"
    )


def _print_db_creds_hint(compose_file: str) -> None:
    """Explain the most common migrate failure: a postgres volume with stale creds.

    Postgres only applies POSTGRES_USER/PASSWORD when it first initializes an
    empty data dir. If a volume from an earlier run already exists it keeps the
    original credentials, so freshly-generated ones are rejected ('password
    authentication failed'). Resetting the volume lets it re-initialize.
    """
    print(
        "\n  If the error above is 'password authentication failed', the postgres\n"
        "  volume was initialized with different credentials (e.g. the installer was\n"
        "  re-run, or POSTGRES_PASSWORD changed). Postgres keeps a volume's original\n"
        "  credentials, so reset the database — THIS DESTROYS ITS DATA — then re-run:\n"
        f"    docker compose -f {compose_file} down\n"
        "    docker volume ls | grep postgres_data   # find this project's volumes\n"
        "    docker volume rm <name> <name>_backups"
    )


def _reset_stale_db_volume(
    env: str, repo_root: Path, compose_file: str, input_fn, run_fn
) -> None:
    """Offer to drop a stale postgres volume before bringing the stack up.

    Prevents the silent 'password authentication failed' trap: a postgres volume
    surviving from a previous run keeps its original credentials, which never
    match the freshly-generated ones. Interactive and opt-in; only the postgres
    data/backups volumes are removed (Traefik cert + Redis are left intact).
    """
    stale = _stale_postgres_volumes(env, repo_root)
    if not stale:
        return
    print("\n  A postgres volume from a previous run already exists:")
    for v in stale:
        print(f"    {v}")
    print(
        "  It holds the OLD database credentials; this install generated new ones,\n"
        "  and Postgres keeps a volume's original creds — so migrate would fail with\n"
        "  'password authentication failed'."
    )
    answer = input_fn(
        "  Remove it so the database initializes fresh? (DESTROYS its data) [y/N] "
    )
    if answer.strip().lower() in ("y", "yes"):
        run_fn(["docker", "compose", "-f", compose_file, "down"], repo_root)
        _remove_docker_volumes(stale)
        print("  Removed — the database will re-initialize with the new credentials.")
    else:
        print("  Keeping it — migrate will fail until you reset it (see below).")


def _reset_db_volumes(
    env: str, repo_root: Path, compose_file: str, run_fn
) -> None:
    """Non-interactive DB reset: stop the stack and remove its postgres volumes.

    Used when bring-up is config/flag-driven and `destroy` is set, so it must NOT
    prompt. Only this project's postgres data/backups volumes for `env` are
    removed (Redis + Traefik cert volumes are left intact — never `down -v`).
    """
    volumes = _stale_postgres_volumes(env, repo_root)
    print("\n  Resetting the database (destroy=true) for a fresh start ...")
    run_fn(["docker", "compose", "-f", compose_file, "down"], repo_root)
    if volumes:
        for v in volumes:
            print(f"    removing volume: {v}")
        _remove_docker_volumes(volumes)
    print("  Done — the database will initialize fresh.")


def offer_bring_up(
    repo_root: Path,
    *,
    env: str = "dev",
    domain: str = "",
    can_prompt: bool = True,
    input_fn=input,
    run_fn=_run_compose_step,
) -> None:
    """Offer to build and start the `env` stack ('dev' default, 'prod' via flag).

    Interactive and opt-in: it never runs without an explicit y/yes, skips the
    whole step in non-interactive runs (can_prompt=False) so it never blocks
    automation, and is a no-op when Docker is not installed. The environment is
    chosen up front (dev by default; --production selects prod) rather than
    prompted. On confirmation the build->lock->migrate->createsuperuser->up steps
    run against the matching compose file. domain (when known) is used to print
    the production service URLs.
    """
    if not can_prompt:
        print(
            "\nSkipping stack bring-up (non-interactive run). "
            "Re-run with --start to build & start it, or see the README."
        )
        return
    if not _docker_available():
        print(
            "\nDocker not found on PATH — skipping stack bring-up. "
            "See the README for the build/up commands."
        )
        return

    print(f"\n=== Optional: build & start the '{env}' stack ===")
    # Defaults to NO: only an explicit y/yes proceeds; Enter or anything else skips.
    if input_fn(
        f"  Build and start the '{env}' stack now? [y/N] "
    ).strip().lower() not in ("y", "yes"):
        print("  Skipped.")
        return

    compose_file = _COMPOSE_FILES[env]
    _reset_stale_db_volume(env, repo_root, compose_file, input_fn, run_fn)
    _execute_bring_up(
        env,
        repo_root,
        compose_file,
        domain=domain,
        run_fn=run_fn,
        include_superuser=True,
    )


def _execute_bring_up(
    env: str,
    repo_root: Path,
    compose_file: str,
    *,
    domain: str,
    run_fn,
    include_superuser: bool,
) -> None:
    """Run the build->...->up steps for `env` and print the service URLs.

    Shared by the interactive offer_bring_up and the non-interactive start_stack
    (--start) paths. A fatal step stops the sequence; a migrate failure also
    prints the stale-DB-credentials hint. include_superuser=False skips the
    TTY-only createsuperuser step and prints how to create one afterwards.
    """
    print(f"\n  Bringing up the '{env}' stack ({compose_file}) ...")
    for label, argv, fatal in _bring_up_steps(
        env, compose_file, include_superuser=include_superuser
    ):
        print(f"\n  -> {label}: {' '.join(argv)}")
        code = run_fn(argv, repo_root)
        if code == 0:
            continue
        if fatal:
            print(
                f"  '{label}' failed (exit {code}); stopping bring-up.\n"
                "  Fix the issue, then re-run the build/up commands from the README."
            )
            if label == "migrate":
                _print_db_creds_hint(compose_file)
            return
        print(f"  '{label}' did not complete (exit {code}); continuing.")

    if not include_superuser:
        print(
            "\n  No superuser was created (non-interactive). Create one with:\n"
            f"    docker compose -f {compose_file} run --rm django "
            "python manage.py createsuperuser"
        )
    _print_running_urls(env, repo_root, domain)


def start_stack(
    repo_root: Path,
    env: str,
    *,
    domain: str = "",
    reset_db: bool = False,
    include_superuser: bool = False,
    run_fn=_run_compose_step,
) -> None:
    """Build and start the `env` stack — the config "start" / --start path.

    Driven by config ("start"/"destroy") or CLI flags, so the env (dev by
    default, prod via --production) and reset_db are fixed up front — there is no
    dev/prod prompt. A no-op when Docker is missing.

    include_superuser controls the createsuperuser step: include it when a
    terminal is available (so its interactive prompt can run) and skip it on
    --yes / piped / CI runs (where a hint to create one later is printed instead).

    reset_db=True ("destroy") stops the stack and removes this project's postgres
    volume(s) for a fresh database BEFORE building — the explicit way to avoid the
    'password authentication failed' trap on a re-run. reset_db=False only WARNS
    about a surviving volume (never deletes data silently); if migrate then fails
    on stale credentials, the printed hint explains the manual reset.
    """
    if not _docker_available():
        print(
            "\nDocker not found on PATH — skipping start. "
            "See the README for the build/up commands."
        )
        return
    compose_file = _COMPOSE_FILES[env]
    if reset_db:
        _reset_db_volumes(env, repo_root, compose_file, run_fn)
    else:
        stale = _stale_postgres_volumes(env, repo_root)
        if stale:
            print("\n  Warning: a postgres volume from a previous run already exists:")
            for v in stale:
                print(f"    {v}")
            print(
                "  It keeps the OLD credentials, so migrate may fail with 'password\n"
                "  authentication failed'. Reset it (set \"destroy\": true, pass\n"
                "  --destroy, or run manually) — THIS DESTROYS ITS DATA:\n"
                f"    docker compose -f {compose_file} down\n"
                f"    docker volume rm {' '.join(stale)}"
            )
    print(f"\n=== Building & starting the '{env}' stack ===")
    _execute_bring_up(
        env,
        repo_root,
        compose_file,
        domain=domain,
        run_fn=run_fn,
        include_superuser=include_superuser,
    )


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

_EXTERNAL_SECRETS_CHECKLIST = """\
  [ ] MAILGUN_API_KEY / MAILGUN_DOMAIN — set in backend/.envs/.production/.django
  [ ] SENTRY_DSN — set in backend/.envs/.production/.django and frontend/.envs/.production/.next
  [ ] DJANGO_SERVER_EMAIL — set in backend/.envs/.production/.django
  [ ] AWS keys (if media=aws) — set DJANGO_AWS_ACCESS_KEY_ID,
      DJANGO_AWS_SECRET_ACCESS_KEY, DJANGO_AWS_STORAGE_BUCKET_NAME
"""


def print_summary(answers: dict, media: str, modified_files: list[Path]) -> None:
    slug = answers.get("__PROJECT_SLUG__", "")
    print(f"\n{'=' * 60}")
    print(f"  Bootstrap complete — project: {slug}")
    print(f"  Media backend: {media}")
    print(f"  Files modified: {len(modified_files)}")
    print(
        "\n  Secrets generated in:\n"
        "    backend/.envs/  (chmod 600 applied)\n"
        "    frontend/.envs/ (chmod 600 applied)"
    )
    print("\nExternal secrets to set manually:")
    print(_EXTERNAL_SECRETS_CHECKLIST)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def _has_remaining_tokens(repo_root: Path) -> bool | None:
    """Scan a representative sample of files for remaining __TOKEN__ patterns.

    Returns True if any sampled file still contains a token; False if at least
    one sample file exists and none contain tokens; None if no sample files
    exist at all (caller proceeds in that case). Robust to README.md absence.
    """
    token_re = re.compile(r"__[A-Z_]+__")
    candidates = [
        repo_root / "README.md",
        repo_root / "backend" / "config" / "settings" / "base.py",
        repo_root / "backend" / "config" / "settings" / "production.py",
    ]
    any_exist = False
    for f in candidates:
        if not f.exists():
            continue
        any_exist = True
        if token_re.search(f.read_text(encoding="utf-8", errors="replace")):
            return True
    return None if not any_exist else False


def run_bootstrap(
    repo_root: Path,
    answers: dict[str, str],
    media: str,
    dry_run: bool = False,
    keep_script: bool = False,
    force: bool = False,
    interactive: bool = False,
    start: bool = False,
    env: str = "dev",
    reset_db: bool = False,
) -> None:
    """Execute the full bootstrap sequence.

    answers keys must use the token form: '__PROJECT_SLUG__', '__DOMAIN__', etc.
    The run finishes by bringing up the `env` stack ('dev' default, 'prod' via
    --production): when start=True it builds and starts non-interactively via
    start_stack (so it works under --yes/--config), resetting the DB first when
    reset_db=True ('destroy'); otherwise, when interactive, it offers the bring-up
    via offer_bring_up.
    """
    # Step 2: Safety check — .template-marker must be present.
    marker = repo_root / TEMPLATE_MARKER_FILENAME
    if not marker.exists() and not force:
        raise FileNotFoundError(
            f".template-marker not found at {repo_root}. "
            "This does not appear to be a template root. "
            "Use --force to skip this check."
        )

    # Check for remaining tokens (refuse re-run unless --force).
    # Samples README.md plus the settings modules so a deleted README does not
    # silently bypass the guard or block recovery after a partial run.
    if not force and not dry_run and _has_remaining_tokens(repo_root) is False:
        raise RuntimeError(
            "No tokens found in the sampled files. This repo may "
            "already be bootstrapped. Use --force to run anyway."
        )

    # Step 3: Dry-run print and exit.
    if dry_run:
        token_map = dict(answers)  # blank optionals included → tokens resolve to ''
        modified = token_replace_pass(repo_root, token_map, dry_run=True)
        slug = answers.get("__PROJECT_SLUG__", "<slug>")
        print(f"[dry-run] Would modify {len(modified)} files")
        print(f"[dry-run] Would rename backend/__PROJECT_SLUG__/ → backend/{slug}/")
        print(f"[dry-run] Media variant: {media}")
        if media == "local":
            print("[dry-run] Would wire nginx media sidecar (compose + Traefik)")
        else:
            print(
                "[dry-run] Would remove backend/compose/production/nginx/ (media=aws)"
            )
        print("[dry-run] Would strip TEMPLATE:MEDIA markers from production configs")
        print("[dry-run] Would generate env files (keeping their .example seeds)")
        print(
            "[dry-run] Would remove template scaffolding (TEMPLATE.md, pyproject.toml, tests/)"
        )
        if start:
            reset_note = ", resetting the DB first" if reset_db else ""
            su_note = (
                " (prompts for createsuperuser)"
                if interactive
                else " (skips createsuperuser — no TTY)"
            )
            print(
                f"[dry-run] Would build & start the '{env}' stack"
                f"{reset_note}{su_note}"
            )
        elif interactive:
            print(f"[dry-run] Would offer to build & start the '{env}' stack")
        return

    # Replace every token, including blank optional fields (author/description),
    # so they resolve to '' rather than leaving literal __TOKEN__ in the output.
    token_map = dict(answers)

    # Step 4: Token-replace pass (file contents; dir still named __PROJECT_SLUG__/).
    modified = token_replace_pass(repo_root, token_map)

    # Step 5: Rename package directory (AFTER token pass).
    slug = answers.get("__PROJECT_SLUG__", "")
    if slug:
        rename_package_dir(repo_root, slug)

    # Step 6: Media block rewrite (Django settings) + media-serving infrastructure.
    prod_py = repo_root / "backend" / "config" / "settings" / "production.py"
    if prod_py.exists():
        write_media_block(prod_py, media)
    apply_media_infrastructure(
        repo_root,
        media,
        slug=answers.get("__PROJECT_SLUG__", ""),
        domain=answers.get("__DOMAIN__", ""),
    )
    # Strip the TEMPLATE:MEDIA markers now that every region is wired/cleared.
    for rel in _MEDIA_MARKER_FILES:
        strip_template_markers(repo_root / rel)
    # Drop the template-only CI bootstrap steps: a generated project's CI runs
    # its checks directly (there is no template left to bootstrap).
    strip_marked_region(repo_root / ".github" / "workflows" / "ci.yml", "TEMPLATE:CI")

    # Step 7: Generate env files + secrets from the committed .example seeds.
    generate_env_files(repo_root, media, domain=answers.get("__DOMAIN__", ""))

    # Step 8: Remove template-only scaffolding (dev test harness + template docs).
    remove_template_scaffolding(repo_root)

    # Step 9: Self-delete (unless --keep-script).
    # Note: --keep-script preserves BOTH this script AND .template-marker.
    # A re-run then requires --force because tokens are consumed.
    if not keep_script:
        self_delete(repo_root)

    # Step 10: Summary.
    print_summary(answers, media, modified)

    # Step 11: Build & start the `env` stack (dev default; prod via --production).
    # --start runs it non-interactively (works under --yes/--config); otherwise
    # offer_bring_up offers it, self-skipping when can_prompt is False or Docker
    # is absent.
    domain = answers.get("__DOMAIN__", "")
    if start:
        # Include createsuperuser when a terminal is available (interactive);
        # --yes / piped / CI runs skip it (no TTY) and print a how-to hint.
        start_stack(
            repo_root,
            env,
            domain=domain,
            reset_db=reset_db,
            include_superuser=interactive,
        )
    else:
        offer_bring_up(repo_root, env=env, domain=domain, can_prompt=interactive)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _prompt(label: str, default: str = "", required: bool = True) -> str:
    prompt_str = f"  {label}"
    if default:
        prompt_str += f" [{default}]"
    prompt_str += ": "
    while True:
        value = input(prompt_str).strip() or default
        if required and not value:
            print("  (required)")
            continue
        return value


def _slug_from_name(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    if slug and slug[0].isdigit():
        slug = "p_" + slug
    return slug


def _collect_answers_interactive() -> tuple[dict[str, str], str]:
    print("\n=== Bootstrap — project values ===\n")
    project_name = _prompt("Project name (display, e.g. AcmeCorp)")
    suggested_slug = _slug_from_name(project_name)

    while True:
        slug = _prompt("Project slug (Python identifier)", default=suggested_slug)
        err = validate_slug(slug)
        if err:
            print(f"  Error: {err}")
        else:
            break

    while True:
        domain = _prompt("Domain (e.g. example.com)")
        err = validate_domain(domain)
        if err:
            print(f"  Error: {err}")
        else:
            break

    author_name = _prompt("Author name", required=False)
    while True:
        # Required: feeds Let's Encrypt ACME, Django ADMINS, and pyproject.toml.
        author_email = _prompt("Author email", required=True)
        err = validate_email(author_email)
        if err:
            print(f"  Error: {err}")
        else:
            break

    description = _prompt("Project description (tagline)", required=False)

    while True:
        timezone = _prompt("Timezone", default="UTC", required=False)
        err = validate_timezone(timezone)
        if err:
            print(f"  Error: {err}")
        else:
            timezone = timezone or "UTC"
            break

    while True:
        media = _prompt("Media backend [local/aws]", default="local").lower()
        if media in ("local", "aws"):
            break
        print("  Choose 'local' or 'aws'.")

    answers = {
        "__PROJECT_NAME__": project_name,
        "__PROJECT_SLUG__": slug,
        "__DOMAIN__": domain,
        "__AUTHOR_NAME__": author_name,
        "__AUTHOR_EMAIL__": author_email,
        "__PROJECT_DESCRIPTION__": description,
        "__TIMEZONE__": timezone,
    }
    return answers, media


def _parse_bringup(raw: dict) -> dict:
    """Resolve the optional post-bootstrap bring-up directives from config JSON.

    Keys (all optional; absent -> no bring-up):
      "start":   false | "dev" | "prod"   (true is treated as "dev") — build &
                 start that stack after bootstrap, non-interactively.
      "destroy": false | true             — reset (destroy) this project's DB
                 volume for a fresh start before bring-up.

    Returns {"start": bool, "env": "dev"|"prod", "destroy": bool}. Unknown values
    are treated as their safe default (no start / no destroy).
    """
    raw_start = raw.get("start", False)
    start, env = False, "dev"
    if isinstance(raw_start, bool):
        start = raw_start
    elif isinstance(raw_start, str):
        v = raw_start.strip().lower()
        if v in ("dev", "local", "true", "yes"):
            start, env = True, "dev"
        elif v in ("prod", "production"):
            start, env = True, "prod"
    raw_destroy = raw.get("destroy", False)
    destroy = (
        raw_destroy
        if isinstance(raw_destroy, bool)
        else str(raw_destroy).strip().lower() in ("true", "yes", "y", "1")
    )
    return {"start": start, "env": env, "destroy": destroy}


def _collect_bringup_from_config(config_path: Path) -> dict:
    """Read the bring-up directives ("start"/"destroy") from the config JSON."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return _parse_bringup(raw)


def _collect_answers_from_config(config_path: Path) -> tuple[dict[str, str], str]:
    """Load answers from a JSON config file.

    Expected JSON keys:
    {
        "project_name": "...",       // required
        "project_slug": "...",       // required
        "domain": "...",             // required
        "author_name": "...",        // optional
        "author_email": "...",       // optional
        "project_description": "...",// optional
        "timezone": "UTC",           // optional, default UTC
        "media": "local",            // required: "local" or "aws"
        "start": "dev",              // optional: false | "dev" | "prod" — auto build & start
        "destroy": false             // optional: true to reset the DB volume first
    }

    The "start"/"destroy" bring-up directives are parsed separately by
    _collect_bringup_from_config / _parse_bringup; this function ignores them.
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    media = raw.get("media", "local").lower()
    answers = {
        "__PROJECT_NAME__": raw.get("project_name", ""),
        "__PROJECT_SLUG__": raw.get("project_slug", ""),
        "__DOMAIN__": raw.get("domain", ""),
        "__AUTHOR_NAME__": raw.get("author_name", ""),
        "__AUTHOR_EMAIL__": raw.get("author_email", ""),
        "__PROJECT_DESCRIPTION__": raw.get("project_description", ""),
        "__TIMEZONE__": raw.get("timezone", "UTC"),
    }
    return answers, media


def _validate_answers(answers: dict[str, str], media: str) -> list[str]:
    errors = []
    err = validate_slug(answers.get("__PROJECT_SLUG__", ""))
    if err:
        errors.append(f"project_slug: {err}")
    err = validate_domain(answers.get("__DOMAIN__", ""))
    if err:
        errors.append(f"domain: {err}")
    email = answers.get("__AUTHOR_EMAIL__", "")
    err = validate_email(email)
    if err:
        errors.append(f"author_email: {err}")
    elif not email.strip():
        # Required (not just for prod targeting): the template always generates a
        # production stack whose Traefik bakes author_email into TRAEFIK_ACME_EMAIL,
        # and an empty value also yields a malformed Django ADMINS entry. So a
        # dev-first bootstrap must supply it too, or the eventual prod deploy
        # silently fails Let's Encrypt cert issuance.
        errors.append(
            "author_email: required — it feeds Let's Encrypt ACME "
            "(TRAEFIK_ACME_EMAIL), Django ADMINS, and pyproject.toml; an empty "
            "value blocks certificate issuance on first production deploy."
        )
    tz = answers.get("__TIMEZONE__", "")
    err = validate_timezone(tz)
    if err:
        errors.append(f"timezone: {err}")
    if media not in ("local", "aws"):
        errors.append(f"media: must be 'local' or 'aws', got {media!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap this template repo into a new project."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes and exit without modifying anything.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="Path to a JSON answers file (non-interactive mode).",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt."
    )
    parser.add_argument(
        "--keep-script",
        action="store_true",
        help="Do not delete this script and .template-marker after running. "
        "A re-run also requires --force.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if tokens are not found (already bootstrapped).",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="After bootstrapping, build & start the stack non-interactively "
        "(works with --yes/--config). Brings up dev by default, or prod with "
        "--production. Skips the TTY-only createsuperuser step; create one "
        "afterwards with the printed command.",
    )
    parser.add_argument(
        "--production",
        "--prod",
        dest="production",
        action="store_true",
        help="Target the production stack for bring-up (default: dev). Affects "
        "both the interactive offer and --start.",
    )
    parser.add_argument(
        "--destroy",
        action="store_true",
        help="When bringing up the stack, first reset (destroy) this project's "
        "database volume for a fresh start. Same as \"destroy\": true in the "
        "config JSON. DESTROYS the existing DB data for the chosen env.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    # The interactive bring-up OFFER needs a TTY (its y/N prompt + createsuperuser).
    # Gate on an actual terminal — not on --config — so reading answers from a
    # file still offers the bring-up at a TTY; --yes and piped/CI runs stay silent
    # (use --start to bring the stack up without prompts).
    interactive = not args.yes and sys.stdin.isatty()

    # Collect answers (+ optional "start"/"destroy" bring-up directives from JSON).
    bringup = {"start": False, "env": "dev", "destroy": False}
    if args.config:
        answers, media = _collect_answers_from_config(Path(args.config))
        bringup = _collect_bringup_from_config(Path(args.config))
    else:
        answers, media = _collect_answers_interactive()

    # CLI flags override / combine with the config directives. Bring-up env: dev
    # by default; "start": "prod" or --production selects prod.
    env = "prod" if args.production else bringup["env"]
    start = args.start or bringup["start"]
    reset_db = args.destroy or bringup["destroy"]

    # Validate. author_email is mandatory — it feeds the Let's Encrypt ACME email
    # baked into the production Traefik, plus Django ADMINS and pyproject.toml.
    errors = _validate_answers(answers, media)
    if errors:
        for e in errors:
            print(f"  Validation error — {e}", file=sys.stderr)
        return 1

    # Confirm (unless --yes or --dry-run).
    if not args.yes and not args.dry_run:
        print("\nAbout to bootstrap:")
        for k, v in answers.items():
            print(f"  {k} = {v!r}")
        print(f"  media = {media!r}")
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return 0

    run_bootstrap(
        repo_root=repo_root,
        answers=answers,
        media=media,
        dry_run=args.dry_run,
        keep_script=args.keep_script,
        force=args.force,
        interactive=interactive,
        start=start,
        env=env,
        reset_db=reset_db,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
