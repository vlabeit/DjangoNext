"""Unit and integration tests for install.py.

Run from repo root:
    python -m pytest tests/ -v
    python -m pytest tests/ --cov=install --cov-report=term-missing
"""

import json
import re
import stat
import string as _string
import sys
from pathlib import Path

import pytest

# install.py lives at the repo root — one level above this file's parent.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import install  # noqa: E402


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


class TestSlugValidator:
    def test_accepts_valid(self):
        for v in ("myproject", "my_project_2"):
            assert install.validate_slug(v) is None, v

    def test_rejects_invalid(self):
        # uppercase, leading digit, hyphen, empty, spaces, keyword
        for v in ("MyProject", "2project", "my-project", "", "my project", "import"):
            assert install.validate_slug(v) is not None, v

    def test_keyword_error_mentions_keyword(self):
        err = install.validate_slug("class")
        assert err is not None and "keyword" in err.lower()


class TestDomainValidator:
    def test_accepts_valid(self):
        for v in ("example.com", "sub.example.co.uk"):
            assert install.validate_domain(v) is None, v

    def test_rejects_invalid(self):
        # empty, no TLD, leading/trailing dot, scheme, path
        for v in (
            "",
            "localhost",
            ".example.com",
            "example.com.",
            "https://example.com",
            "example.com/path",
        ):
            assert install.validate_domain(v) is not None, v


class TestEmailValidator:
    def test_accepts_valid_and_empty(self):
        # author_email is optional → empty string is permitted
        for v in ("user@example.com", ""):
            assert install.validate_email(v) is None, v

    def test_rejects_invalid(self):
        for v in ("userexample.com", "user@", "@example.com"):
            assert install.validate_email(v) is not None, v


class TestTimezoneValidator:
    def test_accepts_valid_and_empty(self):
        # empty → use the default (UTC). Note: the literal __TIMEZONE__ placeholder
        # is intentionally NOT accepted — like the slug/domain/email validators,
        # validate_timezone rejects its own token (its contract is "non-empty must
        # be a real IANA zone"); the un-bootstrapped value is never validated.
        for v in ("UTC", "America/New_York", ""):
            assert install.validate_timezone(v) is None, v

    def test_rejects_unknown(self):
        assert install.validate_timezone("Mars/Olympus") is not None


# ---------------------------------------------------------------------------
# Token-replace unit tests
# ---------------------------------------------------------------------------


class TestTokenReplace:
    """Tests for install.replace_tokens(text, token_map) -> str."""

    def test_simple_replacement(self):
        result = install.replace_tokens(
            "Hello __PROJECT_NAME__!",
            {"__PROJECT_NAME__": "Acme"},
        )
        assert result == "Hello Acme!"

    def test_multiple_tokens_same_line(self):
        result = install.replace_tokens(
            "slug=__PROJECT_SLUG__ domain=__DOMAIN__",
            {"__PROJECT_SLUG__": "acme", "__DOMAIN__": "acme.com"},
        )
        assert result == "slug=acme domain=acme.com"

    def test_no_match_returns_original(self):
        text = "no tokens here"
        assert install.replace_tokens(text, {"__X__": "y"}) == text

    def test_substring_boundary_domain_before_slug(self):
        # __DOMAIN__ must be replaced before __PROJECT_SLUG__ so that
        # '__DOMAIN__' is not first corrupted to '<slug>.co.il'
        text = "HOST=__DOMAIN__ DB=__PROJECT_SLUG__db"
        result = install.replace_tokens(
            text,
            {"__DOMAIN__": "acme.com", "__PROJECT_SLUG__": "acme"},
        )
        assert result == "HOST=acme.com DB=acmedb"

    def test_domain_not_corrupted_when_slug_is_prefix(self):
        # Simulates: slug='acme', domain='acme.com'
        # If slug replaced first: 'acme.com' → 'acmeacme.com' — WRONG
        # Correct ordering: domain first yields 'acme.com' → 'acme.com'
        text = "__DOMAIN__,www.__DOMAIN__"
        result = install.replace_tokens(
            text,
            {"__DOMAIN__": "acme.com", "__PROJECT_SLUG__": "acme"},
        )
        assert result == "acme.com,www.acme.com"

    def test_token_at_start_and_end_of_line(self):
        result = install.replace_tokens(
            "__PROJECT_SLUG__\n__PROJECT_SLUG__",
            {"__PROJECT_SLUG__": "myapp"},
        )
        assert result == "myapp\nmyapp"

    def test_empty_map_no_change(self):
        text = "__PROJECT_SLUG__ stays"
        assert install.replace_tokens(text, {}) == text

    def test_substituted_value_is_not_rescanned(self):
        # Single-pass: a value that contains another token literal is emitted
        # verbatim, never re-expanded by a later substitution. (Multi-pass would
        # corrupt '__PROJECT_SLUG__' here into the slug value 'myapp'.)
        result = install.replace_tokens(
            "__PROJECT_NAME__",
            {"__PROJECT_NAME__": "__PROJECT_SLUG__", "__PROJECT_SLUG__": "myapp"},
        )
        assert result == "__PROJECT_SLUG__"

    def test_free_text_token_literal_survives(self):
        # Realistic: a user types the literal '__PROJECT_SLUG__' as the project
        # NAME (an unvalidated free-text field). It must reach the output intact.
        result = install.replace_tokens(
            "title = __PROJECT_NAME__\npkg = __PROJECT_SLUG__",
            {"__PROJECT_NAME__": "__PROJECT_SLUG__", "__PROJECT_SLUG__": "acme"},
        )
        assert result == "title = __PROJECT_SLUG__\npkg = acme"

    def test_empty_string_key_is_ignored(self):
        # An empty token key would match at every position (zero-width); it must
        # be skipped so it never corrupts the text.
        result = install.replace_tokens(
            "__PROJECT_SLUG__ x",
            {"": "Z", "__PROJECT_SLUG__": "a"},
        )
        assert result == "a x"


# ---------------------------------------------------------------------------
# Ignore-list / binary-sniff unit tests
# ---------------------------------------------------------------------------


class TestIgnoreList:
    """Tests for install.should_skip_path(path, repo_root) -> bool."""

    def test_skips_expected_paths(self, tmp_path):
        # skip-dirs (any component), lockfiles, and the template's own machinery
        skip = (
            ".git/config",
            ".venv/lib/site.py",
            "frontend/node_modules/react/index.js",
            "backend/__pycache__/foo.pyc",
            "backend/staticfiles/app.css",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "Cargo.lock",
            "install.py",
            "TEMPLATE.md",
            "tests/test_install.py",  # holds __TOKEN__ literals as test data
        )
        for rel in skip:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
            assert install.should_skip_path(p, tmp_path) is True, rel

    def test_does_not_skip_tokenizable_files(self, tmp_path):
        # uv.lock carries the project name token and MUST be rewritten so
        # `uv sync --locked` works after the rename; .py and .example are normal.
        keep = ("uv.lock", "settings.py", ".django.example")
        for rel in keep:
            p = tmp_path / rel
            p.write_text('name = "__PROJECT_SLUG__"\n')
            assert install.should_skip_path(p, tmp_path) is False, rel

    def test_skips_binary_by_null_byte(self, tmp_path):
        p = tmp_path / "image.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")  # PNG header with null byte
        assert install.should_skip_path(p, tmp_path) is True


# ---------------------------------------------------------------------------
# Media-block writer unit tests
# ---------------------------------------------------------------------------

MARKER_START = "# >>> TEMPLATE:MEDIA <<<"
MARKER_END = "# >>> TEMPLATE:MEDIA:END <<<"

AWS_BLOCK_SNIPPET = "S3Storage"
LOCAL_BLOCK_SNIPPET = 'MEDIA_URL = "/media/"'
LOCAL_BLOCK_FORBIDDEN_SNIPPET = "aws_s3_domain"  # must NOT appear in local variant


class TestMediaBlockWriter:
    """Tests for install.write_media_block(production_py_path, variant)."""

    def _make_production_py(self, tmp_path: Path, inner_content: str) -> Path:
        content = (
            f"# preamble\n{MARKER_START}\n{inner_content}\n{MARKER_END}\n# postamble\n"
        )
        p = tmp_path / "production.py"
        p.write_text(content)
        return p

    def test_aws_variant_contains_s3storage(self, tmp_path):
        p = self._make_production_py(tmp_path, "# old content")
        install.write_media_block(p, "aws")
        text = p.read_text()
        assert AWS_BLOCK_SNIPPET in text

    def test_local_variant_contains_media_url(self, tmp_path):
        p = self._make_production_py(tmp_path, "# old content")
        install.write_media_block(p, "local")
        text = p.read_text()
        assert LOCAL_BLOCK_SNIPPET in text

    def test_local_variant_has_no_aws_s3_domain_variable(self, tmp_path):
        p = self._make_production_py(tmp_path, "# old content")
        install.write_media_block(p, "local")
        text = p.read_text()
        assert LOCAL_BLOCK_FORBIDDEN_SNIPPET not in text

    def test_markers_preserved_after_write(self, tmp_path):
        p = self._make_production_py(tmp_path, "# initial")
        install.write_media_block(p, "aws")
        text = p.read_text()
        assert MARKER_START in text
        assert MARKER_END in text

    def test_preamble_and_postamble_preserved(self, tmp_path):
        p = self._make_production_py(tmp_path, "# initial")
        install.write_media_block(p, "local")
        text = p.read_text()
        assert "# preamble" in text
        assert "# postamble" in text

    def test_idempotent_aws(self, tmp_path):
        p = self._make_production_py(tmp_path, "# initial")
        install.write_media_block(p, "aws")
        first = p.read_text()
        install.write_media_block(p, "aws")
        second = p.read_text()
        assert first == second

    def test_idempotent_local(self, tmp_path):
        p = self._make_production_py(tmp_path, "# initial")
        install.write_media_block(p, "local")
        first = p.read_text()
        install.write_media_block(p, "local")
        second = p.read_text()
        assert first == second

    def test_raises_if_markers_missing(self, tmp_path):
        p = tmp_path / "production.py"
        p.write_text("# no markers here\n")
        with pytest.raises((ValueError, RuntimeError)):
            install.write_media_block(p, "local")

    def test_rejects_unknown_variant(self, tmp_path):
        p = self._make_production_py(tmp_path, "# initial")
        with pytest.raises(ValueError, match="variant"):
            install.write_media_block(p, "ftp")

    def test_local_media_url_is_plain_string_not_fstring(self, tmp_path):
        """MEDIA_URL in the local block must be a plain string, not an f-string."""
        p = self._make_production_py(tmp_path, "# initial")
        install.write_media_block(p, "local")
        text = p.read_text()
        inner = text.split(MARKER_START)[1].split(MARKER_END)[0]
        # f-string form would be: f"...{aws_s3_domain}..." — both must be absent.
        assert 'f"' not in inner
        assert "aws_s3_domain" not in inner


# ---------------------------------------------------------------------------
# Generic marked-region writer + media-serving infrastructure
# ---------------------------------------------------------------------------


class TestWriteMarkedRegion:
    def _file(self, tmp_path, indent=""):
        p = tmp_path / "x.yml"
        p.write_text(
            f"before\n{indent}# >>> T:AG <<<\n{indent}# >>> T:AG:END <<<\nafter\n"
        )
        return p

    def test_fills_region(self, tmp_path):
        p = self._file(tmp_path)
        install.write_marked_region(p, "T:AG", "  hello: 1")
        text = p.read_text()
        assert "  hello: 1" in text
        assert "# >>> T:AG <<<" in text and "# >>> T:AG:END <<<" in text

    def test_clear_with_empty_body(self, tmp_path):
        p = self._file(tmp_path)
        install.write_marked_region(p, "T:AG", "  hello: 1")
        install.write_marked_region(p, "T:AG", "")
        text = p.read_text()
        assert "hello" not in text
        assert "# >>> T:AG <<<" in text  # markers preserved

    def test_idempotent(self, tmp_path):
        p = self._file(tmp_path)
        install.write_marked_region(p, "T:AG", "  a: 1")
        first = p.read_text()
        install.write_marked_region(p, "T:AG", "  a: 1")
        assert p.read_text() == first

    def test_preserves_marker_indentation(self, tmp_path):
        p = self._file(tmp_path, indent="    ")
        install.write_marked_region(p, "T:AG", "      x: 1")
        text = p.read_text()
        assert "    # >>> T:AG <<<" in text
        assert "    # >>> T:AG:END <<<" in text

    def test_raises_without_markers(self, tmp_path):
        p = tmp_path / "y.yml"
        p.write_text("no markers here\n")
        with pytest.raises(ValueError, match="Markers"):
            install.write_marked_region(p, "T:AG", "x")


class TestApplyMediaInfrastructure:
    def _repo(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        _make_minimal_fixture(root)
        return root

    def _compose(self, root):
        return (root / "docker-compose.production.yml").read_text()

    def _dynamic(self, root):
        return (
            root / "backend" / "compose" / "production" / "traefik" / "dynamic.yml"
        ).read_text()

    def test_local_wires_nginx_sidecar(self, tmp_path):
        root = self._repo(tmp_path)
        install.apply_media_infrastructure(
            root, "local", slug="acme", domain="acme.io"
        )
        compose, dynamic = self._compose(root), self._dynamic(root)
        assert "production_django_media: {}" in compose  # volume declared
        assert "production_django_media:/app/acme/media" in compose  # mounted on django
        assert "acme_production_nginx" in compose  # nginx service
        assert "nginx-media-secure-router" in dynamic  # traefik router
        assert (
            "(Host(`acme.io`) || Host(`www.acme.io`)) && PathPrefix(`/media`)"
            in dynamic
        )
        assert "http://nginx:80" in dynamic  # traefik backend

    def test_aws_leaves_regions_empty(self, tmp_path):
        root = self._repo(tmp_path)
        install.apply_media_infrastructure(root, "aws", slug="acme", domain="acme.io")
        compose, dynamic = self._compose(root), self._dynamic(root)
        assert "nginx" not in compose  # no nginx service (markers are UPPERCASE)
        assert "production_django_media" not in compose
        assert "nginx" not in dynamic

    def test_idempotent_local(self, tmp_path):
        root = self._repo(tmp_path)
        install.apply_media_infrastructure(
            root, "local", slug="acme", domain="acme.io"
        )
        first = self._compose(root)
        install.apply_media_infrastructure(
            root, "local", slug="acme", domain="acme.io"
        )
        assert self._compose(root) == first

    def test_tolerates_missing_files(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        install.apply_media_infrastructure(
            root, "local", slug="acme", domain="acme.io"
        )  # no raise


# ---------------------------------------------------------------------------
# Repository template regressions
# ---------------------------------------------------------------------------


class TestRepositoryTemplateRegressions:
    def test_template_docs_reference_existing_installer(self):
        docs = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "TEMPLATE.md",
        ]
        for path in docs:
            text = path.read_text()
            assert "bootstrap.py" not in text, f"stale bootstrap.py reference in {path}"
            assert "python3 install.py" in text, f"missing install.py command in {path}"

    def test_production_django_router_handles_www_api_paths(self):
        dynamic_yml = (
            REPO_ROOT
            / "backend"
            / "compose"
            / "production"
            / "traefik"
            / "dynamic.yml"
        ).read_text()
        assert (
            "(Host(`__DOMAIN__`) || Host(`www.__DOMAIN__`)) && "
            "(PathPrefix(`/api`) || PathPrefix(`/static`) || PathPrefix(`/media`))"
        ) in dynamic_yml

    def test_ci_creates_local_env_files_before_compose(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
        setup_index = workflow.find("name: Create local env files")
        compose_index = workflow.find("docker/bake-action")

        assert setup_index != -1, "CI must create real local env files"
        assert compose_index != -1, "CI workflow should still run Docker Compose"
        assert setup_index < compose_index, "Env files must exist before Compose runs"
        assert (
            "cp backend/.envs/.local/.django.example backend/.envs/.local/.django"
            in workflow
        )
        assert (
            "cp backend/.envs/.local/.postgres.example "
            "backend/.envs/.local/.postgres"
        ) in workflow
        assert (
            "cp frontend/.envs/.local/.next.example frontend/.envs/.local/.next"
            in workflow
        )


# ---------------------------------------------------------------------------
# Credential generator unit tests
# ---------------------------------------------------------------------------


class TestCredentialGenerators:
    """Tests for install.generate_secret_key(), install.generate_admin_url(),
    install.generate_password(), install.generate_short_id()."""

    def test_secret_key_min_length(self):
        key = install.generate_secret_key()
        assert len(key) >= 50

    def test_secret_key_url_safe_chars(self):
        key = install.generate_secret_key()
        allowed = set(_string.ascii_letters + _string.digits + "-_")
        assert all(c in allowed for c in key), f"Unsafe char in key: {key!r}"

    def test_secret_key_no_dollar_sign(self):
        # Run many times to probabilistically cover random space
        for _ in range(20):
            assert "$" not in install.generate_secret_key()

    def test_secret_key_no_space(self):
        for _ in range(20):
            assert " " not in install.generate_secret_key()

    def test_admin_url_ends_with_slash(self):
        url = install.generate_admin_url()
        assert url.endswith("/")

    def test_admin_url_min_length(self):
        # The "admin/" prefix and trailing "/" are fixed; the random middle is
        # the actual protection. Matches cookiecutter-django's DJANGO_ADMIN_URL:
        # a 32-character random segment.
        url = install.generate_admin_url()
        suffix = url[len("admin/") : -1]
        assert len(suffix) == 32

    def test_admin_url_suffix_is_alphanumeric(self):
        # cookiecutter-django uses digits + ASCII letters only (no punctuation,
        # no url-safe "-"/"_"), so the obscured path stays clean in URLs.
        allowed = set(_string.ascii_letters + _string.digits)
        suffix = install.generate_admin_url()[len("admin/") : -1]
        assert all(c in allowed for c in suffix)

    def test_admin_url_under_admin_prefix(self):
        # Must live under "admin/" so Traefik's PathPrefix(/admin) routes it to
        # Django in production; a fully random path 404s via the Next.js catch-all.
        url = install.generate_admin_url()
        assert url.startswith("admin/")
        assert len(url) > len("admin/") + 1  # has a real random suffix

    def test_admin_url_random_suffix_varies(self):
        # The bit after "admin/" is the actual protection — it must be random.
        urls = {install.generate_admin_url() for _ in range(5)}
        assert len(urls) == 5

    def test_password_min_length(self):
        pw = install.generate_password()
        assert len(pw) >= 24

    def test_password_url_safe_chars(self):
        pw = install.generate_password()
        allowed = set(_string.ascii_letters + _string.digits + "-_")
        assert all(c in allowed for c in pw)

    def test_two_secret_keys_are_different(self):
        assert install.generate_secret_key() != install.generate_secret_key()

    def test_two_passwords_are_different(self):
        assert install.generate_password() != install.generate_password()

    def test_short_id_is_nonempty_string(self):
        sid = install.generate_short_id()
        assert isinstance(sid, str)
        assert len(sid) > 0


# ---------------------------------------------------------------------------
# Dry-run no-change test
# ---------------------------------------------------------------------------

FIXTURE_TOKEN_MAP = {
    "__PROJECT_NAME__": "Acme App",
    "__PROJECT_SLUG__": "acmeapp",
    "__DOMAIN__": "acme.example.com",
    "__AUTHOR_NAME__": "Jane Doe",
    "__AUTHOR_EMAIL__": "jane@acme.example.com",
    "__PROJECT_DESCRIPTION__": "An example project",
    "__TIMEZONE__": "UTC",
}


def _make_minimal_fixture(root: Path) -> None:
    """Create a minimal repo fixture that mirrors the real repo's token surface."""
    # .template-marker
    (root / ".template-marker").touch()

    # production.py with TEMPLATE:MEDIA markers
    prod_dir = root / "backend" / "config" / "settings"
    prod_dir.mkdir(parents=True)
    (prod_dir / "production.py").write_text(
        "ALLOWED_HOSTS = ['__DOMAIN__']\n"
        "# >>> TEMPLATE:MEDIA <<<\n"
        "# aws block placeholder\n"
        "# >>> TEMPLATE:MEDIA:END <<<\n"
        "EMAIL_SUBJECT_PREFIX = '[__PROJECT_NAME__]'\n"
    )

    # Production compose with the media-infrastructure marker regions.
    (root / "docker-compose.production.yml").write_text(
        "volumes:\n"
        "  production_redis_data: {}\n"
        "  # >>> TEMPLATE:MEDIA:VOLUME <<<\n"
        "  # >>> TEMPLATE:MEDIA:VOLUME:END <<<\n"
        "services:\n"
        "  django: &django\n"
        "    image: __PROJECT_SLUG___production_django\n"
        "    command: /start\n"
        "    # >>> TEMPLATE:MEDIA:MOUNT <<<\n"
        "    # >>> TEMPLATE:MEDIA:MOUNT:END <<<\n"
        "  # >>> TEMPLATE:MEDIA:NGINX <<<\n"
        "  # >>> TEMPLATE:MEDIA:NGINX:END <<<\n"
    )
    # Traefik dynamic config with the media router/service marker regions.
    traefik_dir = root / "backend" / "compose" / "production" / "traefik"
    traefik_dir.mkdir(parents=True)
    (traefik_dir / "dynamic.yml").write_text(
        "http:\n"
        "  routers:\n"
        "    # >>> TEMPLATE:MEDIA:ROUTER <<<\n"
        "    # >>> TEMPLATE:MEDIA:ROUTER:END <<<\n"
        "  services:\n"
        "    # >>> TEMPLATE:MEDIA:SERVICE <<<\n"
        "    # >>> TEMPLATE:MEDIA:SERVICE:END <<<\n"
    )

    # uv.lock carries the project's own package name (must track pyproject.toml).
    (root / "backend" / "uv.lock").write_text(
        "[[package]]\n"
        'name = "__PROJECT_SLUG__"\n'
        'version = "0.1.0"\n'
        'source = { virtual = "." }\n'
    )

    # Package directory
    pkg = root / "backend" / "__PROJECT_SLUG__"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("# __PROJECT_SLUG__ package\n")

    # Example env files
    local_env_dir = root / "backend" / ".envs" / ".local"
    local_env_dir.mkdir(parents=True)
    (local_env_dir / ".django.example").write_text(
        "CELERY_FLOWER_USER=debug\nCELERY_FLOWER_PASSWORD=debug\n"
    )
    (local_env_dir / ".postgres.example").write_text(
        "POSTGRES_DB=__PROJECT_SLUG__\n"
        "POSTGRES_USER=__PROJECT_SLUG__\n"
        "POSTGRES_PASSWORD=CHANGE_ME_dev_password\n"
    )

    prod_env_dir = root / "backend" / ".envs" / ".production"
    prod_env_dir.mkdir(parents=True)
    (prod_env_dir / ".django.example").write_text(
        "DJANGO_SECRET_KEY=CHANGE_ME__generate_a_long_random_secret\n"
        "DJANGO_ADMIN_URL=CHANGE_ME_random_slug/\n"
        "DJANGO_ALLOWED_HOSTS=__DOMAIN__,www.__DOMAIN__\n"
        "CELERY_FLOWER_USER=CHANGE_ME\n"
        "CELERY_FLOWER_PASSWORD=CHANGE_ME\n"
        "MAILGUN_API_KEY=CHANGE_ME\n"
        "SENTRY_DSN=CHANGE_ME\n"
        "# AWS\n"
        "DJANGO_AWS_ACCESS_KEY_ID=\n"
        "DJANGO_AWS_SECRET_ACCESS_KEY=\n"
        "DJANGO_AWS_STORAGE_BUCKET_NAME=\n"
    )
    (prod_env_dir / ".postgres.example").write_text(
        "POSTGRES_DB=__PROJECT_SLUG__\n"
        "POSTGRES_USER=CHANGE_ME\n"
        "POSTGRES_PASSWORD=CHANGE_ME__use_a_strong_password\n"
    )

    frontend_local_env_dir = root / "frontend" / ".envs" / ".local"
    frontend_local_env_dir.mkdir(parents=True)
    (frontend_local_env_dir / ".next.example").write_text("NODE_ENV=development\n")
    (frontend_local_env_dir / "playwright.example").write_text(
        "PLAYWRIGHT_TEST_BASE_URL=http://next:3000\n"
    )

    frontend_prod_env_dir = root / "frontend" / ".envs" / ".production"
    frontend_prod_env_dir.mkdir(parents=True)
    (frontend_prod_env_dir / ".next.example").write_text("NODE_ENV=production\n")
    (frontend_prod_env_dir / ".playwright.example").write_text(
        "PLAYWRIGHT_TEST_BASE_URL=https://__DOMAIN__\n"
    )

    # A text file with all tokens
    (root / "README.md").write_text(
        "# __PROJECT_NAME__\n"
        "__PROJECT_DESCRIPTION__\n"
        "Domain: __DOMAIN__\n"
        "By __AUTHOR_NAME__ <__AUTHOR_EMAIL__>\n"
        "slug: __PROJECT_SLUG__\n"
        "timezone: __TIMEZONE__\n"
    )

    # A binary file (should be skipped)
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    # install.py itself (should NOT be modified)
    (root / "install.py").write_text("TOKEN_PATTERN = '__PROJECT_SLUG__'\n")


def _snapshot_tree(root: Path) -> dict:
    """Return {relative_path_str: file_bytes} for all files."""
    snap = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p.relative_to(root))] = p.read_bytes()
    return snap


class TestDryRunNoChange:
    """--dry-run must not modify any file."""

    def test_dry_run_leaves_tree_unchanged(self, tmp_path):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)

        before = _snapshot_tree(fixture)

        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=True,
            keep_script=False,
            force=False,
        )

        after = _snapshot_tree(fixture)
        assert before == after, "Dry-run must not modify any file"


# ---------------------------------------------------------------------------
# Integration tests — full bootstrap run (one per media variant)
# ---------------------------------------------------------------------------


class TestIntegrationLocal:
    """Full bootstrap run with media='local'."""

    @pytest.fixture
    def bootstrapped(self, tmp_path):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=False,
            keep_script=False,
            force=False,
        )
        return fixture

    def test_no_remaining_tokens_in_text_files(self, bootstrapped):
        """Zero __TOKEN__ occurrences must remain in any non-binary text file."""
        token_re = re.compile(r"__[A-Z_]+__")
        for p in bootstrapped.rglob("*"):
            if not p.is_file():
                continue
            # skip binaries
            try:
                text = p.read_text(errors="strict")
            except (UnicodeDecodeError, OSError):
                continue
            matches = token_re.findall(text)
            assert not matches, f"Remaining tokens in {p}: {matches}"

    def test_package_dir_renamed(self, bootstrapped):
        new_pkg = bootstrapped / "backend" / FIXTURE_TOKEN_MAP["__PROJECT_SLUG__"]
        assert new_pkg.is_dir(), f"Package dir not renamed: {new_pkg}"
        old_pkg = bootstrapped / "backend" / "__PROJECT_SLUG__"
        assert not old_pkg.exists(), "Old __PROJECT_SLUG__ dir still exists"

    def test_production_py_has_local_media_block(self, bootstrapped):
        prod = (
            bootstrapped / "backend" / "config" / "settings" / "production.py"
        ).read_text()
        assert 'MEDIA_URL = "/media/"' in prod
        assert "S3Storage" not in prod

    def test_aws_keys_absent_in_production_django_when_local(self, bootstrapped):
        """Spec §8: AWS env keys present/absent must match the media choice."""
        prod_django = (
            bootstrapped / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        assert "DJANGO_AWS_ACCESS_KEY_ID" not in prod_django
        assert "DJANGO_AWS_SECRET_ACCESS_KEY" not in prod_django
        assert "DJANGO_AWS_STORAGE_BUCKET_NAME" not in prod_django

    def test_external_keys_remain_blank(self, bootstrapped):
        """Spec §8: externally-provided keys (Mailgun/Sentry) stay blank, not generated."""
        prod_django = (
            bootstrapped / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        assert "MAILGUN_API_KEY=\n" in prod_django
        assert "SENTRY_DSN=\n" in prod_django

    def test_renamed_package_py_compiles(self, bootstrapped):
        """Spec §8: py_compile of the renamed package must pass (no syntax corruption)."""
        import py_compile

        slug_dir = bootstrapped / "backend" / FIXTURE_TOKEN_MAP["__PROJECT_SLUG__"]
        py_compile.compile(str(slug_dir / "__init__.py"), doraise=True)

    def test_uv_lock_name_tracks_slug(self, bootstrapped):
        """uv.lock's root package name must follow the rename so `uv sync --locked` works."""
        uv = (bootstrapped / "backend" / "uv.lock").read_text()
        assert f'name = "{FIXTURE_TOKEN_MAP["__PROJECT_SLUG__"]}"' in uv
        assert "__PROJECT_SLUG__" not in uv
        assert "__PROJECT_SLUG__" not in uv

    def test_nginx_media_sidecar_wired_for_local(self, bootstrapped):
        """media=local must wire the nginx media sidecar into compose + Traefik."""
        slug = FIXTURE_TOKEN_MAP["__PROJECT_SLUG__"]
        domain = FIXTURE_TOKEN_MAP["__DOMAIN__"]
        compose = (bootstrapped / "docker-compose.production.yml").read_text()
        dynamic = (
            bootstrapped
            / "backend"
            / "compose"
            / "production"
            / "traefik"
            / "dynamic.yml"
        ).read_text()
        assert "production_django_media: {}" in compose
        assert f"production_django_media:/app/{slug}/media" in compose
        assert f"{slug}_production_nginx" in compose
        assert "nginx-media-secure-router" in dynamic
        assert (
            f"(Host(`{domain}`) || Host(`www.{domain}`)) && PathPrefix(`/media`)"
            in dynamic
        )
        assert "http://nginx:80" in dynamic

    def test_real_env_files_created(self, bootstrapped):
        expected = [
            "backend/.envs/.local/.django",
            "backend/.envs/.local/.postgres",
            "backend/.envs/.production/.django",
            "backend/.envs/.production/.postgres",
            "frontend/.envs/.local/.next",
            "frontend/.envs/.local/playwright",
            "frontend/.envs/.production/.next",
            "frontend/.envs/.production/.playwright",
        ]
        for rel in expected:
            p = bootstrapped / rel
            assert p.exists(), f"Missing env file: {rel}"

    def test_env_files_have_no_change_me(self, bootstrapped):
        for p in bootstrapped.rglob("*"):
            if p.is_file() and p.suffix != ".example":
                parent_parts = p.parts
                if ".envs" in parent_parts:
                    text = p.read_text()
                    assert "CHANGE_ME" not in text, f"CHANGE_ME found in {p}"

    def test_secret_key_only_in_production_django_env(self, bootstrapped):
        prod_django = (
            bootstrapped / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        local_django = (
            bootstrapped / "backend" / ".envs" / ".local" / ".django"
        ).read_text()
        assert "DJANGO_SECRET_KEY" in prod_django
        assert "DJANGO_SECRET_KEY" not in local_django

    def test_secret_key_length_gte_50(self, bootstrapped):
        prod_django = (
            bootstrapped / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        for line in prod_django.splitlines():
            if line.startswith("DJANGO_SECRET_KEY="):
                value = line.split("=", 1)[1]
                assert len(value) >= 50, f"Secret key too short: {len(value)}"
                break

    def test_env_file_perms_600(self, bootstrapped):
        env_files = [
            "backend/.envs/.local/.django",
            "backend/.envs/.production/.django",
            "backend/.envs/.production/.postgres",
        ]
        for rel in env_files:
            p = bootstrapped / rel
            mode = stat.S_IMODE(p.stat().st_mode)
            assert mode == 0o600, f"{rel} has mode {oct(mode)}, expected 0o600"

    def test_local_flower_creds_preserved_debug_debug(self, bootstrapped):
        local_django = (
            bootstrapped / "backend" / ".envs" / ".local" / ".django"
        ).read_text()
        assert "CELERY_FLOWER_USER=debug" in local_django
        assert "CELERY_FLOWER_PASSWORD=debug" in local_django

    def test_production_flower_creds_randomized(self, bootstrapped):
        prod_django = (
            bootstrapped / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        assert "CELERY_FLOWER_USER=CHANGE_ME" not in prod_django
        assert "CELERY_FLOWER_PASSWORD=CHANGE_ME" not in prod_django

    def test_install_py_self_deleted(self, bootstrapped):
        assert not (bootstrapped / "install.py").exists()

    def test_template_marker_deleted(self, bootstrapped):
        assert not (bootstrapped / ".template-marker").exists()

    def test_two_runs_produce_different_secrets(self, tmp_path):
        fixture1 = tmp_path / "repo1"
        fixture1.mkdir()
        _make_minimal_fixture(fixture1)
        install.run_bootstrap(
            repo_root=fixture1,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=False,
            keep_script=False,
            force=False,
        )

        fixture2 = tmp_path / "repo2"
        fixture2.mkdir()
        _make_minimal_fixture(fixture2)
        install.run_bootstrap(
            repo_root=fixture2,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=False,
            keep_script=False,
            force=False,
        )

        prod_django_1 = (
            fixture1 / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        prod_django_2 = (
            fixture2 / "backend" / ".envs" / ".production" / ".django"
        ).read_text()

        def _extract_key(text):
            for line in text.splitlines():
                if line.startswith("DJANGO_SECRET_KEY="):
                    return line.split("=", 1)[1]
            return None

        k1 = _extract_key(prod_django_1)
        k2 = _extract_key(prod_django_2)
        assert k1 is not None and k2 is not None
        assert k1 != k2, "Two runs must produce different secret keys"

    def test_binary_file_untouched(self, bootstrapped):
        png = bootstrapped / "image.png"
        assert png.exists()
        assert b"\x00" in png.read_bytes()  # null byte intact

    def test_install_py_tokens_not_corrupted(self, tmp_path):
        """With --keep-script, install.py's own token literals must not be replaced."""
        fixture = tmp_path / "repo_keep"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=False,
            keep_script=True,
            force=False,
        )
        bs_text = (fixture / "install.py").read_text()
        assert "__PROJECT_SLUG__" in bs_text, (
            "install.py token literals should survive when --keep-script is used"
        )


class TestIntegrationAws:
    """Full bootstrap run with media='aws'."""

    @pytest.fixture
    def bootstrapped_aws(self, tmp_path):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="aws",
            dry_run=False,
            keep_script=False,
            force=False,
        )
        return fixture

    def test_production_py_has_s3_storage(self, bootstrapped_aws):
        prod = (
            bootstrapped_aws / "backend" / "config" / "settings" / "production.py"
        ).read_text()
        assert "S3Storage" in prod

    def test_production_py_has_no_filesystem_media_url(self, bootstrapped_aws):
        prod = (
            bootstrapped_aws / "backend" / "config" / "settings" / "production.py"
        ).read_text()
        # The plain '/media/' form should not be present in the aws variant
        assert 'MEDIA_URL = "/media/"' not in prod

    def test_aws_env_keys_present_in_production_django(self, bootstrapped_aws):
        prod_django = (
            bootstrapped_aws / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        assert "DJANGO_AWS_ACCESS_KEY_ID" in prod_django
        assert "DJANGO_AWS_SECRET_ACCESS_KEY" in prod_django
        assert "DJANGO_AWS_STORAGE_BUCKET_NAME" in prod_django

    def test_aws_keys_are_blank(self, bootstrapped_aws):
        """AWS keys must be present but blank (user fills them in)."""
        prod_django = (
            bootstrapped_aws / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        for line in prod_django.splitlines():
            if line.startswith("DJANGO_AWS_ACCESS_KEY_ID="):
                assert line == "DJANGO_AWS_ACCESS_KEY_ID=", f"AWS key not blank: {line}"
            if line.startswith("DJANGO_AWS_SECRET_ACCESS_KEY="):
                assert line == "DJANGO_AWS_SECRET_ACCESS_KEY=", (
                    f"AWS secret not blank: {line}"
                )

    def test_external_keys_remain_blank(self, bootstrapped_aws):
        """Spec §8: externally-provided keys (Mailgun/Sentry) stay blank, not generated."""
        prod_django = (
            bootstrapped_aws / "backend" / ".envs" / ".production" / ".django"
        ).read_text()
        assert "MAILGUN_API_KEY=\n" in prod_django
        assert "SENTRY_DSN=\n" in prod_django

    def test_no_nginx_sidecar_for_aws(self, bootstrapped_aws):
        """media=aws serves media from S3 — no nginx sidecar / media volume."""
        compose = (bootstrapped_aws / "docker-compose.production.yml").read_text()
        assert "nginx" not in compose
        assert "production_django_media" not in compose


# ---------------------------------------------------------------------------
# Additional coverage tests — slug helper, validate_answers, config loading, main CLI
# ---------------------------------------------------------------------------


class TestSlugFromName:
    """Tests for install._slug_from_name()."""

    def test_simple_name(self):
        assert install._slug_from_name("Acme") == "acme"

    def test_spaces_become_underscores(self):
        assert install._slug_from_name("My Project") == "my_project"

    def test_leading_digit_prefixed(self):
        assert install._slug_from_name("123corp") == "p_123corp"

    def test_special_chars_removed(self):
        result = install._slug_from_name("Acme-Corp!")
        assert re.match(r"[a-z][a-z0-9_]*", result)

    def test_all_lowercase(self):
        result = install._slug_from_name("AcmeCorp")
        assert result == result.lower()


class TestValidateAnswers:
    """Tests for install._validate_answers()."""

    _VALID = {
        "__PROJECT_SLUG__": "myapp",
        "__DOMAIN__": "myapp.example.com",
        "__AUTHOR_EMAIL__": "dev@myapp.example.com",
        "__TIMEZONE__": "UTC",
    }

    def test_valid_answers_no_errors(self):
        errors = install._validate_answers(self._VALID, "local")
        assert errors == []

    def test_invalid_slug_produces_error(self):
        answers = dict(self._VALID, **{"__PROJECT_SLUG__": "MyApp"})
        errors = install._validate_answers(answers, "local")
        assert any("project_slug" in e for e in errors)

    def test_invalid_domain_produces_error(self):
        answers = dict(self._VALID, **{"__DOMAIN__": "not-a-domain"})
        errors = install._validate_answers(answers, "local")
        assert any("domain" in e for e in errors)

    def test_invalid_media_produces_error(self):
        errors = install._validate_answers(self._VALID, "ftp")
        assert any("media" in e for e in errors)

    def test_invalid_email_produces_error(self):
        answers = dict(self._VALID, **{"__AUTHOR_EMAIL__": "notanemail"})
        errors = install._validate_answers(answers, "local")
        assert any("author_email" in e for e in errors)

    def test_empty_author_email_rejected(self):
        # author_email is required (feeds Let's Encrypt ACME / Django ADMINS /
        # pyproject.toml) even for a dev-first bootstrap — the production stack is
        # always generated, so an empty value silently breaks the eventual deploy.
        answers = dict(self._VALID, **{"__AUTHOR_EMAIL__": ""})
        errors = install._validate_answers(answers, "local")
        assert any("author_email" in e for e in errors)

    def test_whitespace_only_author_email_rejected(self):
        answers = dict(self._VALID, **{"__AUTHOR_EMAIL__": "   "})
        errors = install._validate_answers(answers, "local")
        assert any("author_email" in e for e in errors)


class TestCollectAnswersFromConfig:
    """Tests for install._collect_answers_from_config()."""

    def test_loads_all_fields(self, tmp_path):
        config = {
            "project_name": "TestApp",
            "project_slug": "testapp",
            "domain": "test.example.com",
            "author_name": "Test Author",
            "author_email": "test@test.example.com",
            "project_description": "A test.",
            "timezone": "UTC",
            "media": "aws",
        }
        cfg_file = tmp_path / "answers.json"
        cfg_file.write_text(json.dumps(config))
        answers, media = install._collect_answers_from_config(cfg_file)
        assert answers["__PROJECT_SLUG__"] == "testapp"
        assert answers["__DOMAIN__"] == "test.example.com"
        assert media == "aws"

    def test_defaults_media_to_local(self, tmp_path):
        config = {"project_name": "T", "project_slug": "t", "domain": "t.example.com"}
        cfg_file = tmp_path / "a.json"
        cfg_file.write_text(json.dumps(config))
        _, media = install._collect_answers_from_config(cfg_file)
        assert media == "local"

    def test_defaults_timezone_to_utc(self, tmp_path):
        config = {"project_name": "T", "project_slug": "t", "domain": "t.example.com"}
        cfg_file = tmp_path / "a.json"
        cfg_file.write_text(json.dumps(config))
        answers, _ = install._collect_answers_from_config(cfg_file)
        assert answers["__TIMEZONE__"] == "UTC"


class TestParseBringup:
    """The optional "start"/"destroy" bring-up directives in the config JSON."""

    def test_default_is_no_start_no_destroy(self):
        assert install._parse_bringup({}) == {
            "start": False,
            "env": "dev",
            "destroy": False,
        }

    def test_start_dev(self):
        b = install._parse_bringup({"start": "dev"})
        assert b["start"] is True
        assert b["env"] == "dev"

    def test_start_prod_and_production_synonym(self):
        assert install._parse_bringup({"start": "prod"})["env"] == "prod"
        assert install._parse_bringup({"start": "production"})["env"] == "prod"
        assert install._parse_bringup({"start": "prod"})["start"] is True

    def test_start_true_means_dev(self):
        b = install._parse_bringup({"start": True})
        assert b["start"] is True
        assert b["env"] == "dev"

    def test_start_false_or_unknown_does_not_start(self):
        assert install._parse_bringup({"start": False})["start"] is False
        assert install._parse_bringup({"start": "staging"})["start"] is False

    def test_destroy_bool_and_string(self):
        assert install._parse_bringup({"destroy": True})["destroy"] is True
        assert install._parse_bringup({"destroy": "yes"})["destroy"] is True
        assert install._parse_bringup({"destroy": False})["destroy"] is False
        assert install._parse_bringup({})["destroy"] is False

    def test_collect_bringup_from_config_file(self, tmp_path):
        cfg = tmp_path / "a.json"
        cfg.write_text(json.dumps({"start": "prod", "destroy": True}))
        assert install._collect_bringup_from_config(cfg) == {
            "start": True,
            "env": "prod",
            "destroy": True,
        }


class TestMainCLI:
    """Tests for the install.main() CLI entry point using --config + --yes."""

    def _write_config(self, tmp_path: Path, **overrides) -> Path:
        config = {
            "project_name": "CLIApp",
            "project_slug": "cliapp",
            "domain": "cliapp.example.com",
            "author_name": "CLI Author",
            "author_email": "cli@cliapp.example.com",
            "project_description": "A CLI test app.",
            "timezone": "UTC",
            "media": "local",
        }
        config.update(overrides)
        cfg_file = tmp_path / "answers.json"
        cfg_file.write_text(json.dumps(config))
        return cfg_file

    def test_main_with_config_and_yes_runs_successfully(self, tmp_path, monkeypatch):
        """main() with --config + --yes bootstraps the fixture successfully."""
        # Set up fixture in tmp_path/repo
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)

        # Patch __file__ in bootstrap module so repo_root resolves to our fixture.
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))

        result = install.main(
            [
                "--config",
                str(cfg_file),
                "--yes",
            ]
        )
        assert result == 0
        # install.py deleted
        assert not (fixture / "install.py").exists()

    def test_main_returns_1_on_validation_error(self, tmp_path, monkeypatch):
        cfg_file = self._write_config(tmp_path, project_slug="BadSlug")
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))

        result = install.main(["--config", str(cfg_file), "--yes"])
        assert result == 1

    def test_main_dry_run_returns_0(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))

        result = install.main(["--config", str(cfg_file), "--dry-run"])
        assert result == 0
        # Dry-run: install.py must still exist
        assert (fixture / "install.py").exists()

    def test_main_start_flag_invokes_start_stack_dev_default(self, tmp_path, monkeypatch):
        """--start with --config/--yes brings up the stack non-interactively (dev)."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(["--config", str(cfg_file), "--yes", "--start"])
        assert result == 0
        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args[1] == "dev"  # default env
        assert kwargs.get("domain") == "cliapp.example.com"

    def test_main_production_flag_selects_prod(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(
            ["--config", str(cfg_file), "--yes", "--start", "--production"]
        )
        assert result == 0
        assert calls[0][0][1] == "prod"

    def test_main_prod_alias_selects_prod(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(
            ["--config", str(cfg_file), "--yes", "--start", "--prod"]
        )
        assert result == 0
        assert calls[0][0][1] == "prod"

    def test_config_start_dev_drives_bringup_without_flag(self, tmp_path, monkeypatch):
        """"start": "dev" in the JSON brings up the stack — no --start flag needed."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path, start="dev")
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(["--config", str(cfg_file), "--yes"])
        assert result == 0
        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args[1] == "dev"
        assert kwargs.get("reset_db") is False

    def test_config_start_prod_and_destroy(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path, start="prod", destroy=True)
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(["--config", str(cfg_file), "--yes"])
        assert result == 0
        args, kwargs = calls[0]
        assert args[1] == "prod"
        assert kwargs.get("reset_db") is True

    def test_destroy_flag_overrides_config_false(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path, start="dev")  # destroy absent -> False
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        calls = []
        monkeypatch.setattr(install, "start_stack", lambda *a, **k: calls.append((a, k)))

        result = install.main(["--config", str(cfg_file), "--yes", "--destroy"])
        assert result == 0
        assert calls[0][1].get("reset_db") is True

    def test_config_without_start_does_not_bring_up(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg_file = self._write_config(tmp_path)  # no "start" key
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        start_calls, offer_calls = [], []
        monkeypatch.setattr(
            install, "start_stack", lambda *a, **k: start_calls.append((a, k))
        )
        monkeypatch.setattr(
            install, "offer_bring_up", lambda *a, **k: offer_calls.append((a, k))
        )

        result = install.main(["--config", str(cfg_file), "--yes"])
        assert result == 0
        assert start_calls == []           # no auto-start
        assert len(offer_calls) == 1       # falls back to the (self-skipping) offer


class TestRenamePackageDirEdgeCases:
    """Edge cases for rename_package_dir."""

    def test_already_renamed_returns_new_path(self, tmp_path):
        """If __PROJECT_SLUG__ dir is missing but slug dir exists, returns slug path."""
        slug = "myapp"
        new = tmp_path / "backend" / slug
        new.mkdir(parents=True)
        result = install.rename_package_dir(tmp_path, slug)
        assert result == new

    def test_missing_both_raises(self, tmp_path):
        """If neither old nor new dir exists, raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            install.rename_package_dir(tmp_path, "nonexistent")


class TestRunBootstrapEdgeCases:
    """Edge cases for run_install."""

    def test_no_template_marker_raises_without_force(self, tmp_path):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        # No .template-marker placed
        with pytest.raises(FileNotFoundError):
            install.run_bootstrap(
                repo_root=fixture,
                answers=FIXTURE_TOKEN_MAP,
                media="local",
                dry_run=False,
                keep_script=False,
                force=False,
            )

    def test_already_bootstrapped_raises_without_force(self, tmp_path):
        """If README has no tokens, run_bootstrap raises RuntimeError."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        (fixture / ".template-marker").touch()
        # README without any tokens
        (fixture / "README.md").write_text("# Already bootstrapped\nNo tokens here.\n")

        with pytest.raises(RuntimeError, match="already be bootstrapped"):
            install.run_bootstrap(
                repo_root=fixture,
                answers=FIXTURE_TOKEN_MAP,
                media="local",
                dry_run=False,
                keep_script=False,
                force=False,
            )

    def test_force_skips_marker_check(self, tmp_path):
        """With --force, run proceeds even without .template-marker."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        # Build minimal fixture WITHOUT .template-marker
        _make_minimal_fixture(fixture)
        (fixture / ".template-marker").unlink()

        # Should not raise
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            dry_run=False,
            keep_script=False,
            force=True,
        )

    def test_dry_run_with_no_readme(self, tmp_path):
        """Dry-run on fixture without README.md still works."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        (fixture / "README.md").unlink()

        before = _snapshot_tree(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="aws",
            dry_run=True,
            keep_script=False,
            force=False,
        )
        after = _snapshot_tree(fixture)
        assert before == after

    def test_guard_samples_settings_when_readme_absent(self, tmp_path):
        """Re-run guard still fires off settings files when README.md is gone."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        (fixture / ".template-marker").touch()
        settings = fixture / "backend" / "config" / "settings"
        settings.mkdir(parents=True)
        # base.py without tokens → already-bootstrapped state, no README present
        (settings / "base.py").write_text("TIME_ZONE = 'UTC'\n")
        with pytest.raises(RuntimeError, match="already be bootstrapped"):
            install.run_bootstrap(
                repo_root=fixture,
                answers=FIXTURE_TOKEN_MAP,
                media="local",
                dry_run=False,
                keep_script=False,
                force=False,
            )

    def test_blank_optional_fields_leave_no_raw_tokens(self, tmp_path):
        """Optional fields left blank must still consume their tokens (→ ''),
        not leave literal __AUTHOR_NAME__/__AUTHOR_EMAIL__/__PROJECT_DESCRIPTION__
        in the generated project (e.g. pyproject.toml, README, base.html)."""
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        answers = {
            "__PROJECT_NAME__": "Acme App",
            "__PROJECT_SLUG__": "acmeapp",
            "__DOMAIN__": "acme.example.com",
            "__AUTHOR_NAME__": "",
            "__AUTHOR_EMAIL__": "",
            "__PROJECT_DESCRIPTION__": "",
            "__TIMEZONE__": "UTC",
        }
        install.run_bootstrap(
            repo_root=fixture,
            answers=answers,
            media="local",
            dry_run=False,
            keep_script=False,
            force=False,
        )
        readme = (fixture / "README.md").read_text()
        leftover = re.findall(r"__[A-Z_]+__", readme)
        assert not leftover, f"raw tokens left after blank optionals: {leftover}"


# ---------------------------------------------------------------------------
# Interactive prompt + confirmation-branch coverage
# ---------------------------------------------------------------------------


class TestInteractiveAndConfirmation:
    """Cover _collect_answers_interactive() and the main() confirmation branch."""

    def test_collect_answers_interactive_with_defaults(self, monkeypatch):
        responses = iter(
            [
                "AcmeCorp",  # project name
                "",  # slug → default 'acmecorp'
                "acme.example.com",  # domain
                "",  # author name
                "jane@acme.example.com",  # author email (now required)
                "",  # description
                "",  # timezone → UTC
                "",  # media → local
            ]
        )
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(responses))
        answers, media = install._collect_answers_interactive()
        assert answers["__PROJECT_SLUG__"] == "acmecorp"
        assert answers["__DOMAIN__"] == "acme.example.com"
        assert answers["__TIMEZONE__"] == "UTC"
        assert media == "local"

    def test_main_confirmation_abort_returns_0(self, tmp_path, monkeypatch):
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        cfg = {
            "project_name": "AbortApp",
            "project_slug": "abortapp",
            "domain": "abort.example.com",
            "author_email": "abort@abort.example.com",
            "media": "local",
        }
        cfg_file = tmp_path / "answers.json"
        cfg_file.write_text(json.dumps(cfg))
        monkeypatch.setattr(install, "__file__", str(fixture / "install.py"))
        # No --yes → main() prompts for confirmation; answer 'n' to abort.
        monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
        result = install.main(["--config", str(cfg_file)])
        assert result == 0
        assert (fixture / "install.py").exists()  # aborted: not self-deleted


# ---------------------------------------------------------------------------
# Marker / doc-section stripping unit tests
# ---------------------------------------------------------------------------


class TestStripTemplateMarkers:
    """strip_template_markers removes TEMPLATE:MEDIA marker pairs cleanly."""

    def test_filled_region_keeps_body_drops_markers(self, tmp_path):
        p = tmp_path / "production.py"
        p.write_text(
            "A = 1\n"
            "# >>> TEMPLATE:MEDIA <<<\n"
            "MEDIA_URL = '/media/'\n"
            "# >>> TEMPLATE:MEDIA:END <<<\n"
            "B = 2\n"
        )
        install.strip_template_markers(p)
        assert p.read_text() == "A = 1\nMEDIA_URL = '/media/'\nB = 2\n"

    def test_empty_region_collapses_preceding_blank(self, tmp_path):
        p = tmp_path / "compose.yml"
        p.write_text(
            "flower: 1\n"
            "\n"
            "  # >>> TEMPLATE:MEDIA:NGINX <<<\n"
            "  # >>> TEMPLATE:MEDIA:NGINX:END <<<\n"
            "tls: 2\n"
        )
        install.strip_template_markers(p)
        assert p.read_text() == "flower: 1\ntls: 2\n"

    def test_empty_region_without_preceding_blank(self, tmp_path):
        p = tmp_path / "compose.yml"
        p.write_text(
            "  redis: {}\n"
            "  # >>> TEMPLATE:MEDIA:VOLUME <<<\n"
            "  # >>> TEMPLATE:MEDIA:VOLUME:END <<<\n"
            "\n"
            "networks:\n"
        )
        install.strip_template_markers(p)
        assert p.read_text() == "  redis: {}\n\nnetworks:\n"

    def test_no_markers_is_noop(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("nothing here\n")
        install.strip_template_markers(p)
        assert p.read_text() == "nothing here\n"

    def test_missing_file_is_noop(self, tmp_path):
        install.strip_template_markers(tmp_path / "nope.txt")  # must not raise

    def test_unclosed_marker_raises(self, tmp_path):
        # A start marker with no matching :END must fail loudly rather than
        # silently consuming the marker and dropping trailing content.
        p = tmp_path / "broken.py"
        p.write_text(
            "A = 1\n"
            "# >>> TEMPLATE:MEDIA <<<\n"
            "MEDIA_URL = '/media/'\n"  # no :END marker
        )
        with pytest.raises(ValueError):
            install.strip_template_markers(p)


class TestStripReadmeDocSection:
    def test_removes_doc_section_and_markers(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text(
            "# Proj\n"
            "\n"
            "> tagline\n"
            "\n"
            "<!-- TEMPLATE:DOC:START -->\n"
            "## Use this template\n"
            "stuff\n"
            "---\n"
            "<!-- TEMPLATE:DOC:END -->\n"
            "\n"
            "Body.\n"
        )
        install.strip_readme_doc_section(p)
        assert p.read_text() == "# Proj\n\n> tagline\n\nBody.\n"

    def test_noop_without_markers(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text("# Proj\n\nBody.\n")
        install.strip_readme_doc_section(p)
        assert p.read_text() == "# Proj\n\nBody.\n"


class TestStripMarkedRegion:
    """strip_marked_region deletes a whole '# >>> NAME … <<<' block (body too)."""

    def test_removes_region_body_and_collapses_blank(self, tmp_path):
        # Mirrors the ci.yml shape: a step between two other steps.
        p = tmp_path / "ci.yml"
        p.write_text(
            "      - name: A\n"
            "        run: a\n"
            "\n"
            "      # >>> TEMPLATE:CI <<<\n"
            "      - name: Bootstrap\n"
            "        run: |\n"
            "          python3 install.py --yes\n"
            "      # >>> TEMPLATE:CI:END <<<\n"
            "\n"
            "      - name: B\n"
            "        run: b\n"
        )
        install.strip_marked_region(p, "TEMPLATE:CI")
        assert p.read_text() == (
            "      - name: A\n"
            "        run: a\n"
            "\n"
            "      - name: B\n"
            "        run: b\n"
        )

    def test_no_markers_is_noop(self, tmp_path):
        p = tmp_path / "ci.yml"
        p.write_text("jobs:\n  linter:\n    steps: []\n")
        install.strip_marked_region(p, "TEMPLATE:CI")
        assert p.read_text() == "jobs:\n  linter:\n    steps: []\n"

    def test_missing_file_is_noop(self, tmp_path):
        install.strip_marked_region(tmp_path / "nope.yml", "TEMPLATE:CI")  # no raise

    def test_unclosed_marker_raises(self, tmp_path):
        p = tmp_path / "ci.yml"
        p.write_text("a\n# >>> TEMPLATE:CI <<<\n- step\n")  # no :END
        with pytest.raises(ValueError):
            install.strip_marked_region(p, "TEMPLATE:CI")


class TestSecurityHeaderOwnership:
    """X-Frame-Options: one consistent DENY policy across edge + Django.

    Traefik (the edge) and Django both set X-Frame-Options. They must agree on
    a single value so the effective policy is unambiguous and identical in local
    dev (Django only) and production (edge overrides). DENY is the strict default.
    """

    def test_traefik_frame_options_deny(self):
        dynamic = (
            REPO_ROOT
            / "backend"
            / "compose"
            / "production"
            / "traefik"
            / "dynamic.yml"
        ).read_text()
        assert "customFrameOptionsValue: DENY" in dynamic
        assert "SAMEORIGIN" not in dynamic

    def test_django_frame_options_deny(self):
        base = (
            REPO_ROOT / "backend" / "config" / "settings" / "base.py"
        ).read_text()
        assert 'X_FRAME_OPTIONS = "DENY"' in base

    def test_readme_does_not_advertise_sameorigin(self):
        # The README must not claim the effective X-Frame-Options is SAMEORIGIN;
        # both layers now agree on DENY. (Guards against doc drift on this file
        # shipping into generated projects.)
        readme = (REPO_ROOT / "README.md").read_text()
        assert "SAMEORIGIN" not in readme


# ---------------------------------------------------------------------------
# End-to-end: bootstrap the REAL template; assert no scaffolding survives
# ---------------------------------------------------------------------------

import shutil  # noqa: E402

_REAL_ANSWERS = {
    "__PROJECT_NAME__": "AcmeCorp",
    "__PROJECT_SLUG__": "acmecorp",
    "__DOMAIN__": "acme.example.com",
    "__AUTHOR_NAME__": "Jane Doe",
    "__AUTHOR_EMAIL__": "jane@acme.example.com",
    "__PROJECT_DESCRIPTION__": "Acme tagline.",
    "__TIMEZONE__": "UTC",
}

_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    "node_modules",
    ".venv",
    ".next",
    "staticfiles",
)

_MEDIA_FILES = (
    "backend/config/settings/production.py",
    "docker-compose.production.yml",
    "backend/compose/production/traefik/dynamic.yml",
    "backend/compose/production/django/Dockerfile",
)


def _bootstrap_real_template(tmp_path, media):
    dest = tmp_path / "tmpl"
    shutil.copytree(REPO_ROOT, dest, ignore=_COPY_IGNORE)
    install.run_bootstrap(
        repo_root=dest,
        answers=_REAL_ANSWERS,
        media=media,
        dry_run=False,
        keep_script=False,
        force=False,
    )
    return dest


class TestRealTemplateBootstrapAws:
    @pytest.fixture
    def repo(self, tmp_path):
        return _bootstrap_real_template(tmp_path, "aws")

    def test_no_media_markers_remain(self, repo):
        for rel in _MEDIA_FILES:
            assert "TEMPLATE:MEDIA" not in (repo / rel).read_text(), f"marker in {rel}"

    def test_nginx_build_context_removed(self, repo):
        assert not (repo / "backend/compose/production/nginx").exists()

    def test_dockerfile_has_no_media_block(self, repo):
        dockerfile = (repo / "backend/compose/production/django/Dockerfile").read_text()
        assert "mkdir -p ${APP_HOME}/acmecorp/media" not in dockerfile

    def test_compose_has_no_nginx(self, repo):
        assert "nginx" not in (repo / "docker-compose.production.yml").read_text()

    def test_example_files_kept(self, repo):
        # The .example seeds are committed stand-ins (gitignore tracks them); they
        # must survive bootstrap so a fresh clone has env templates to copy from.
        leftover = [str(p.relative_to(repo)) for p in repo.rglob("*.example")]
        assert leftover, "Expected .example seed files to be kept, found none"

    def test_real_env_files_present(self, repo):
        assert (repo / "backend/.envs/.production/.django").exists()
        assert (repo / "frontend/.envs/.production/.next").exists()

    def test_scaffolding_removed(self, repo):
        assert not (repo / "TEMPLATE.md").exists()
        assert not (repo / "pyproject.toml").exists()
        assert not (repo / "tests").exists()

    def test_readme_doc_section_stripped(self, repo):
        readme = (repo / "README.md").read_text()
        assert "Use this template" not in readme
        assert "TEMPLATE:DOC" not in readme


class TestRealTemplateBootstrapLocal:
    @pytest.fixture
    def repo(self, tmp_path):
        return _bootstrap_real_template(tmp_path, "local")

    def test_no_media_markers_remain(self, repo):
        for rel in _MEDIA_FILES:
            assert "TEMPLATE:MEDIA" not in (repo / rel).read_text(), f"marker in {rel}"

    def test_nginx_build_context_kept(self, repo):
        assert (repo / "backend/compose/production/nginx").is_dir()

    def test_dockerfile_has_media_block(self, repo):
        dockerfile = (repo / "backend/compose/production/django/Dockerfile").read_text()
        assert "mkdir -p ${APP_HOME}/acmecorp/media" in dockerfile

    def test_nginx_sidecar_wired(self, repo):
        assert (
            "acmecorp_production_nginx"
            in (repo / "docker-compose.production.yml").read_text()
        )

    def test_example_files_kept(self, repo):
        assert list(repo.rglob("*.example")), "Expected .example seed files to be kept"

    def test_ci_bootstrap_steps_stripped(self, repo):
        # The generated project's CI runs its checks directly; the template-only
        # bootstrap steps (and their markers) must be gone.
        ci = (repo / ".github/workflows/ci.yml").read_text()
        assert "TEMPLATE:CI" not in ci, "CI markers left in the generated project"
        assert "install.py" not in ci, "template bootstrap step left in generated CI"
        assert "Bootstrap template into a real project" not in ci


# ---------------------------------------------------------------------------
# Stack bring-up (optional, interactive post-install)
# ---------------------------------------------------------------------------


def _queued_input(*answers):
    """Return an input_fn that yields the given answers in order."""
    it = iter(answers)
    return lambda _prompt="": next(it)


class TestPruneRemoved:
    """The old volume-pruning API must be fully gone (install runs once)."""

    # Prune-SPECIFIC symbols stay gone. (The generic _list_docker_volumes /
    # _remove_docker_volumes helpers were later re-introduced for the bring-up
    # stale-DB-volume preflight — a different, targeted use — so they are NOT
    # asserted absent here.)
    @pytest.mark.parametrize(
        "name",
        [
            "prune_old_volumes",
            "_select_old_volumes",
            "PRUNE_OLD_VOLUMES",
            "_SLUG_TOKEN",
            "_LOCAL_VOLUME_SUFFIXES",
        ],
    )
    def test_symbol_removed(self, name):
        assert not hasattr(install, name)

    def test_old_slug_flag_rejected(self):
        # The --old-slug CLI argument is gone; argparse exits non-zero.
        with pytest.raises(SystemExit):
            install.main(["--old-slug", "foo", "--dry-run"])


def _label_of(argv):
    """Identify a bring-up step from its argv (last token is unambiguous)."""
    last = argv[-1]
    if last == "build":
        return "build"
    if last == "lock":
        return "lock"
    if last == "migrate":
        return "migrate"
    if last == "createsuperuser":
        return "createsuperuser"
    if last == "-d":
        return "up"
    return None


class TestBringUpSteps:
    """Pure step list — command order, compose file, container, fatality."""

    def test_dev_uses_local_compose(self):
        for _label, argv, _fatal in install._bring_up_steps(
            "dev", "docker-compose.local.yml"
        ):
            assert "docker-compose.local.yml" in argv

    def test_dev_order_is_build_lock_migrate_createsuperuser_up(self):
        labels = [label for label, _a, _f in install._bring_up_steps("dev", "c.yml")]
        assert labels == ["build", "lock", "migrate", "createsuperuser", "up"]

    def test_prod_has_no_lock_step(self):
        # The production image has no uv (lockfile baked at build), so 'lock'
        # must be skipped for prod — otherwise it errors with 'uv: not found'.
        labels = [label for label, _a, _f in install._bring_up_steps("prod", "c.yml")]
        assert labels == ["build", "migrate", "createsuperuser", "up"]
        assert "lock" not in labels

    def test_up_is_detached(self):
        steps = {
            label: argv for label, argv, _f in install._bring_up_steps("dev", "c.yml")
        }
        assert steps["up"][-2:] == ["up", "-d"]

    def test_lock_and_migrate_run_in_django_container(self):
        steps = {
            label: argv for label, argv, _f in install._bring_up_steps("dev", "c.yml")
        }
        assert steps["lock"][4:8] == ["run", "--rm", "django", "uv"]
        assert steps["migrate"][4:7] == ["run", "--rm", "django"]

    def test_only_lock_and_createsuperuser_are_non_fatal(self):
        non_fatal = {
            label
            for label, _a, fatal in install._bring_up_steps("dev", "c.yml")
            if not fatal
        }
        assert non_fatal == {"lock", "createsuperuser"}

    def test_include_superuser_false_drops_createsuperuser_dev(self):
        labels = [
            label
            for label, _a, _f in install._bring_up_steps(
                "dev", "c.yml", include_superuser=False
            )
        ]
        assert labels == ["build", "lock", "migrate", "up"]
        assert "createsuperuser" not in labels

    def test_include_superuser_false_drops_createsuperuser_prod(self):
        labels = [
            label
            for label, _a, _f in install._bring_up_steps(
                "prod", "c.yml", include_superuser=False
            )
        ]
        assert labels == ["build", "migrate", "up"]


class TestComposeProjectName:
    def test_lowercases_dir_name(self, tmp_path):
        d = tmp_path / "DjangoNext2"
        d.mkdir()
        assert install._compose_project_name(d) == "djangonext2"

    def test_strips_dots_and_spaces(self, tmp_path):
        d = tmp_path / "My.App 2"
        d.mkdir()
        assert install._compose_project_name(d) == "myapp2"


class TestStalePostgresVolumes:
    def test_prod_matches_only_this_project_production(self, monkeypatch, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        monkeypatch.setattr(
            install,
            "_list_docker_volumes",
            lambda: [
                "proj_production_postgres_data",
                "proj_production_postgres_data_backups",
                "proj_production_redis_data",  # not postgres
                "proj_production_traefik",  # not postgres
                "other_production_postgres_data",  # different project
            ],
        )
        assert set(install._stale_postgres_volumes("prod", d)) == {
            "proj_production_postgres_data",
            "proj_production_postgres_data_backups",
        }

    def test_dev_matches_slug_named_local_volumes(self, monkeypatch, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        monkeypatch.setattr(
            install,
            "_list_docker_volumes",
            lambda: [
                "proj_myslug_local_postgres_data",
                "proj_myslug_local_postgres_data_backups",
                "proj_production_postgres_data",  # wrong scope
            ],
        )
        assert set(install._stale_postgres_volumes("dev", d)) == {
            "proj_myslug_local_postgres_data",
            "proj_myslug_local_postgres_data_backups",
        }

    def test_prefix_boundary_avoids_other_projects(self, monkeypatch, tmp_path):
        d = tmp_path / "app"
        d.mkdir()
        monkeypatch.setattr(
            install,
            "_list_docker_volumes",
            lambda: ["app2_production_postgres_data"],  # 'app2', not 'app'
        )
        assert install._stale_postgres_volumes("prod", d) == []

    def test_empty_project_returns_empty(self):
        assert install._stale_postgres_volumes("prod", Path(".")) == []


class TestStaleVolumePreflight:
    """offer_bring_up offers to drop a stale postgres volume before building."""

    def _run(self, monkeypatch, *, stale, answers):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(
            install, "_stale_postgres_volumes", lambda env, root: list(stale)
        )
        removed = []
        monkeypatch.setattr(
            install, "_remove_docker_volumes", lambda names: removed.extend(names)
        )
        calls = []

        def run_fn(argv, cwd):
            calls.append(argv)
            return 0

        install.offer_bring_up(
            Path("/proj"), env="prod", input_fn=_queued_input(*answers), run_fn=run_fn
        )
        return removed, calls

    def test_removes_stale_volume_on_yes(self, monkeypatch):
        removed, calls = self._run(
            monkeypatch,
            stale=["proj_production_postgres_data", "proj_production_postgres_data_backups"],
            answers=("y", "y"),  # opt-in, remove?
        )
        assert removed == [
            "proj_production_postgres_data",
            "proj_production_postgres_data_backups",
        ]
        assert ["docker", "compose", "-f", "docker-compose.production.yml", "down"] in calls
        # then it proceeds to build the stack
        assert ["docker", "compose", "-f", "docker-compose.production.yml", "build"] in calls

    def test_keeps_stale_volume_on_no(self, monkeypatch):
        removed, calls = self._run(
            monkeypatch,
            stale=["proj_production_postgres_data"],
            answers=("y", "n"),  # opt-in, remove?
        )
        assert removed == []
        assert ["docker", "compose", "-f", "docker-compose.production.yml", "down"] not in calls
        # still proceeds (migrate will likely fail, with the hint)
        assert ["docker", "compose", "-f", "docker-compose.production.yml", "build"] in calls

    def test_no_prompt_when_no_stale_volume(self, monkeypatch):
        # No stale volume -> the interactive reset prompt is skipped entirely; only
        # the opt-in answer is consumed.
        removed, calls = self._run(
            monkeypatch, stale=[], answers=("y",)
        )
        assert removed == []
        assert ["docker", "compose", "-f", "docker-compose.production.yml", "build"] in calls


class TestOfferBringUp:
    """Orchestration — run_fn and input_fn injected; no real docker calls."""

    @pytest.fixture
    def runner(self):
        """A run_fn recorder; configure per-label exit codes via .codes."""
        calls = []
        codes = {}

        def run_fn(argv, cwd):
            calls.append(argv)
            return codes.get(_label_of(argv), 0)

        run_fn.calls = calls
        run_fn.codes = codes
        return run_fn

    @staticmethod
    def _labels(runner):
        return [_label_of(argv) for argv in runner.calls]

    def test_skips_when_not_interactive(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        install.offer_bring_up(
            Path("."),
            can_prompt=False,
            input_fn=_queued_input("y", "dev"),
            run_fn=runner,
        )
        assert runner.calls == []

    def test_skips_when_docker_unavailable(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: False)
        install.offer_bring_up(
            Path("."),
            can_prompt=True,
            input_fn=_queued_input("y", "dev"),
            run_fn=runner,
        )
        assert runner.calls == []

    def test_declined_optin_runs_nothing(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        install.offer_bring_up(Path("."), input_fn=_queued_input("n"), run_fn=runner)
        assert runner.calls == []

    def test_empty_optin_defaults_to_skip(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        install.offer_bring_up(Path("."), input_fn=_queued_input(""), run_fn=runner)
        assert runner.calls == []

    def test_dev_runs_all_steps_against_local_compose(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        assert self._labels(runner) == [
            "build",
            "lock",
            "migrate",
            "createsuperuser",
            "up",
        ]
        assert all("docker-compose.local.yml" in argv for argv in runner.calls)

    def test_prod_uses_production_compose(self, runner, monkeypatch):
        # env is chosen up front (--production), not prompted.
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        install.offer_bring_up(
            Path("."), env="prod", input_fn=_queued_input("yes"), run_fn=runner
        )
        assert all("docker-compose.production.yml" in argv for argv in runner.calls)

    def test_fatal_build_failure_aborts(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["build"] = 1
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        assert self._labels(runner) == ["build"]  # nothing runs after a fatal failure

    def test_fatal_migrate_failure_aborts_before_up(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["migrate"] = 1
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        assert self._labels(runner) == ["build", "lock", "migrate"]
        assert "up" not in self._labels(runner)

    def test_non_fatal_lock_failure_continues(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["lock"] = 2
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        assert self._labels(runner) == [
            "build",
            "lock",
            "migrate",
            "createsuperuser",
            "up",
        ]

    def test_non_fatal_createsuperuser_failure_continues_to_up(
        self, runner, monkeypatch
    ):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["createsuperuser"] = 1
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        assert "up" in self._labels(runner)

    def test_migrate_failure_prints_db_creds_hint(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["migrate"] = 1
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        out = capsys.readouterr().out
        assert "password authentication failed" in out
        assert "docker volume rm" in out
        assert "docker-compose.local.yml down" in out  # compose-file-specific

    def test_non_migrate_failure_does_not_print_db_hint(
        self, runner, monkeypatch, capsys
    ):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        runner.codes["build"] = 1  # fatal, but not the DB step
        install.offer_bring_up(
            Path("."), input_fn=_queued_input("y", "dev"), run_fn=runner
        )
        out = capsys.readouterr().out
        assert "password authentication failed" not in out
        assert "docker volume rm" not in out


class TestStartStack:
    """Non-interactive --start bring-up: no prompts, skips createsuperuser."""

    @pytest.fixture
    def runner(self):
        calls = []
        codes = {}

        def run_fn(argv, cwd):
            calls.append(argv)
            return codes.get(_label_of(argv), 0)

        run_fn.calls = calls
        run_fn.codes = codes
        return run_fn

    @staticmethod
    def _labels(runner):
        return [_label_of(argv) for argv in runner.calls]

    def test_dev_runs_steps_skipping_superuser(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        install.start_stack(Path("."), "dev", run_fn=runner)
        assert self._labels(runner) == ["build", "lock", "migrate", "up"]
        assert "createsuperuser" not in self._labels(runner)
        assert all("docker-compose.local.yml" in argv for argv in runner.calls)

    def test_prod_uses_production_compose(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        install.start_stack(Path("."), "prod", run_fn=runner)
        assert self._labels(runner) == ["build", "migrate", "up"]
        assert all("docker-compose.production.yml" in argv for argv in runner.calls)

    def test_skipped_without_docker(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: False)
        install.start_stack(Path("."), "dev", run_fn=runner)
        assert runner.calls == []

    def test_prints_superuser_hint(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        install.start_stack(Path("."), "dev", run_fn=runner)
        assert "createsuperuser" in capsys.readouterr().out

    def test_warns_about_stale_volume_without_destroying(
        self, runner, monkeypatch, capsys
    ):
        # A non-interactive run must never silently delete data: it only WARNS.
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(
            install,
            "_stale_postgres_volumes",
            lambda env, root: ["proj_production_postgres_data"],
        )
        removed = []
        monkeypatch.setattr(
            install, "_remove_docker_volumes", lambda names: removed.extend(names)
        )
        install.start_stack(Path("."), "prod", run_fn=runner)
        out = capsys.readouterr().out
        assert "proj_production_postgres_data" in out
        assert removed == []
        assert self._labels(runner)[0] == "build"  # still proceeds

    def test_migrate_failure_prints_db_hint_and_stops(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        runner.codes["migrate"] = 1
        install.start_stack(Path("."), "dev", run_fn=runner)
        out = capsys.readouterr().out
        assert "password authentication failed" in out
        assert "up" not in self._labels(runner)  # fatal migrate stops before up

    def test_reset_db_true_downs_and_removes_volumes_before_build(
        self, runner, monkeypatch
    ):
        # "destroy": true -> non-interactively stop the stack and remove this
        # project's postgres volume(s) before building (no prompt).
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(
            install, "_stale_postgres_volumes", lambda env, root: ["p_local_postgres_data"]
        )
        removed = []
        monkeypatch.setattr(
            install, "_remove_docker_volumes", lambda names: removed.extend(names)
        )
        install.start_stack(Path("."), "dev", reset_db=True, run_fn=runner)
        assert removed == ["p_local_postgres_data"]
        down = ["docker", "compose", "-f", "docker-compose.local.yml", "down"]
        assert down in runner.calls
        # down comes before the build step
        assert runner.calls.index(down) < self._labels(runner).index("build")
        assert "createsuperuser" not in self._labels(runner)

    def test_reset_db_false_warns_only_and_removes_nothing(self, runner, monkeypatch):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(
            install, "_stale_postgres_volumes", lambda env, root: ["p_local_postgres_data"]
        )
        removed = []
        monkeypatch.setattr(
            install, "_remove_docker_volumes", lambda names: removed.extend(names)
        )
        install.start_stack(Path("."), "dev", reset_db=False, run_fn=runner)
        assert removed == []
        down = ["docker", "compose", "-f", "docker-compose.local.yml", "down"]
        assert down not in runner.calls

    def test_include_superuser_true_runs_createsuperuser(self, runner, monkeypatch):
        # At a terminal the config/flag-driven start still prompts for a superuser.
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        install.start_stack(Path("."), "dev", include_superuser=True, run_fn=runner)
        assert self._labels(runner) == [
            "build",
            "lock",
            "migrate",
            "createsuperuser",
            "up",
        ]

    def test_include_superuser_false_prints_hint(self, runner, monkeypatch, capsys):
        monkeypatch.setattr(install, "_docker_available", lambda: True)
        monkeypatch.setattr(install, "_stale_postgres_volumes", lambda env, root: [])
        install.start_stack(Path("."), "dev", include_superuser=False, run_fn=runner)
        assert "createsuperuser" not in self._labels(runner)
        assert "createsuperuser" in capsys.readouterr().out  # the how-to hint


class TestBringUpWiring:
    """run_bootstrap always calls offer_bring_up, passing interactivity through."""

    def _run(self, tmp_path, monkeypatch, *, interactive):
        calls = []
        monkeypatch.setattr(
            install, "offer_bring_up", lambda *a, **k: calls.append((a, k))
        )
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            force=True,
            interactive=interactive,
        )
        return calls

    def test_interactive_run_can_prompt_true(self, tmp_path, monkeypatch):
        calls = self._run(tmp_path, monkeypatch, interactive=True)
        assert len(calls) == 1
        _args, kwargs = calls[0]
        assert kwargs.get("can_prompt") is True

    def test_non_interactive_run_can_prompt_false(self, tmp_path, monkeypatch):
        calls = self._run(tmp_path, monkeypatch, interactive=False)
        assert len(calls) == 1
        _args, kwargs = calls[0]
        assert kwargs.get("can_prompt") is False

    def test_start_calls_start_stack_not_offer(self, tmp_path, monkeypatch):
        offer_calls, start_calls = [], []
        monkeypatch.setattr(
            install, "offer_bring_up", lambda *a, **k: offer_calls.append((a, k))
        )
        monkeypatch.setattr(
            install, "start_stack", lambda *a, **k: start_calls.append((a, k))
        )
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            force=True,
            interactive=False,
            start=True,
            env="prod",
        )
        assert offer_calls == []
        assert len(start_calls) == 1
        args, kwargs = start_calls[0]
        assert args[1] == "prod"  # env passed positionally
        # interactive=False -> no TTY -> createsuperuser skipped.
        assert kwargs.get("include_superuser") is False

    def test_start_includes_superuser_when_interactive(self, tmp_path, monkeypatch):
        # At a terminal (interactive=True) the config-driven start still prompts
        # for a superuser — run_bootstrap forwards include_superuser=True.
        start_calls = []
        monkeypatch.setattr(
            install, "start_stack", lambda *a, **k: start_calls.append((a, k))
        )
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            force=True,
            interactive=True,
            start=True,
            env="dev",
        )
        assert len(start_calls) == 1
        assert start_calls[0][1].get("include_superuser") is True

    def test_offer_receives_env(self, tmp_path, monkeypatch):
        # Without --start, run_bootstrap forwards the chosen env to offer_bring_up.
        calls = []
        monkeypatch.setattr(
            install, "offer_bring_up", lambda *a, **k: calls.append((a, k))
        )
        fixture = tmp_path / "repo"
        fixture.mkdir()
        _make_minimal_fixture(fixture)
        install.run_bootstrap(
            repo_root=fixture,
            answers=FIXTURE_TOKEN_MAP,
            media="local",
            force=True,
            interactive=True,
            env="prod",
        )
        assert len(calls) == 1
        _args, kwargs = calls[0]
        assert kwargs.get("env") == "prod"
        assert kwargs.get("can_prompt") is True


class TestReadAdminUrl:
    def test_reads_admin_url_from_production_env(self, tmp_path):
        env = tmp_path / "backend" / ".envs" / ".production"
        env.mkdir(parents=True)
        (env / ".django").write_text(
            "DJANGO_SECRET_KEY=x\nDJANGO_ADMIN_URL=admin/s3cr3t/\nFOO=bar\n"
        )
        assert install._read_admin_url(tmp_path) == "admin/s3cr3t/"

    def test_missing_file_returns_empty(self, tmp_path):
        assert install._read_admin_url(tmp_path) == ""

    def test_missing_key_returns_empty(self, tmp_path):
        env = tmp_path / "backend" / ".envs" / ".production"
        env.mkdir(parents=True)
        (env / ".django").write_text("FOO=bar\n")
        assert install._read_admin_url(tmp_path) == ""


class TestPrintRunningUrls:
    def test_dev_prints_localhost_service_urls(self, capsys):
        install._print_running_urls("dev", Path("."), domain="ignored.example")
        out = capsys.readouterr().out
        assert "http://localhost:3000" in out
        assert "http://localhost:8000/admin/" in out
        assert "docker-compose.local.yml" in out

    def test_prod_prints_domain_urls_with_admin_and_docs_hint(self, tmp_path, capsys):
        env = tmp_path / "backend" / ".envs" / ".production"
        env.mkdir(parents=True)
        (env / ".django").write_text("DJANGO_ADMIN_URL=admin/zzz/\n")
        install._print_running_urls("prod", tmp_path, domain="acme.io")
        out = capsys.readouterr().out
        assert "https://acme.io" in out
        assert "https://acme.io/api/docs/" in out
        assert "admin login required" in out
        assert "https://acme.io/admin/zzz/" in out  # obscured admin path printed
        assert "docker-compose.production.yml" in out

    def test_prod_without_admin_url_still_prints_other_urls(self, tmp_path, capsys):
        install._print_running_urls("prod", tmp_path, domain="acme.io")
        out = capsys.readouterr().out
        assert "https://acme.io/api/docs/" in out
        # No admin line when the env/key is missing, but no crash either.
        assert "/admin/" not in out
