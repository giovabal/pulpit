import sys
import warnings
from pathlib import Path

from webapp_engine.config import (
    ENV_PATH,
    SYSTEM_PATH,
    load_crawl_settings,
    load_structural_settings,
)

from decouple import Config, Csv, RepositoryEnv, UndefinedValueError

# Telethon calls the deprecated asyncio.get_event_loop() during initialisation
# when no loop is running yet (Python 3.12+). The warning is attributed to
# whichever frame asyncio's stacklevel resolves to, so we match on message +
# category only — the text is specific enough to avoid false positives.
warnings.filterwarnings(
    "ignore",
    message="There is no current event loop",
    category=DeprecationWarning,
)

# Under the test runner, silence logging: the suite deliberately exercises
# flood-wait, failed-download, unresolved-reference and parse-failure paths
# whose log records would otherwise flood the output. No test asserts on log
# output (no assertLogs anywhere), so disabling it wholesale is safe. Match the
# `test` subcommand precisely (argv[1]) so a stray "test" argument to another
# command can't accidentally mute logging. Migration 0045 also reads this flag.
TESTING = sys.argv[1:2] == ["test"]
if TESTING:
    import logging

    logging.disable(logging.CRITICAL)


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

MEDIA_ROOT_DIRNAME = "media"
MEDIA_ROOT = BASE_DIR / MEDIA_ROOT_DIRNAME


# ── Configuration loading ─────────────────────────────────────────────────────
# .env (credentials, deployment, Django runtime)  → decouple `config(...)`
# .operations-crawl (TOML)                        → webapp_engine.config.load_crawl_settings()
# .operations-structural (TOML)                   → webapp_engine.config.load_structural_settings()
# .system (APP_VERSION, REPOSITORY_URL)           → decouple `_sys(...)`


class _EmptyRepository:
    """Fallback repository that contains no keys — used when a config file is absent."""

    def __contains__(self, key: str) -> bool:
        return False

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)


# Tests must be hermetic — a developer's local .operations-crawl can flip
# safety-critical knobs like IGNORE_FLOODWAIT=False or CRAWL_FETCH_RECOMMENDED=True,
# which then leak into mocked crawler tests and either hang on 900-second sleeps
# or run code paths the test never primed. When running under `manage.py test`,
# bypass both .operations-* files so every read falls back to its hardcoded default.
_RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

config = Config(RepositoryEnv(str(ENV_PATH)) if ENV_PATH.exists() else _EmptyRepository())
_sys = Config(RepositoryEnv(str(SYSTEM_PATH)) if SYSTEM_PATH.exists() else _EmptyRepository())

_crawl = load_crawl_settings(hermetic=_RUNNING_TESTS)
_structural = load_structural_settings(hermetic=_RUNNING_TESTS)


_ENV_HINTS = {
    "SECRET_KEY": (
        "Generate one with:\n"
        '  python -c "from django.core.management.utils import get_random_secret_key; '
        "print('SECRET_KEY=' + get_random_secret_key())\" >> configuration/.env"
    ),
    "ALLOWED_HOSTS": "Add a comma-separated list, e.g.:\n  ALLOWED_HOSTS=localhost,127.0.0.1",
    "TELEGRAM_API_ID": "Get your API credentials at https://my.telegram.org/apps then add:\n  TELEGRAM_API_ID=...",
    "TELEGRAM_API_HASH": "Get your API credentials at https://my.telegram.org/apps then add:\n  TELEGRAM_API_HASH=...",
    "TELEGRAM_PHONE_NUMBER": (
        "Add your Telegram-registered phone number in international format, e.g.:\n  TELEGRAM_PHONE_NUMBER=+33611223344"
    ),
    "DB_NAME": "Required when DB_ENGINE is postgresql / mysql / mariadb / oracle. Add:\n  DB_NAME=...",
}


def _required(key, cast=str):
    """Read a required setting from configuration/.env, exiting with a helpful message when missing.

    Bare ``decouple.config(key)`` raises ``UndefinedValueError`` whose default
    stack trace buries the actual problem in a wall of import frames. Catch it
    here and print a focused, actionable error pointing the user at the .env
    file and (where useful) the one-liner that fixes it.
    """
    try:
        return config(key, cast=cast)
    except UndefinedValueError:
        sys.stderr.write(f"\nMissing required configuration: {key} is not set in {ENV_PATH}\n")
        if not ENV_PATH.exists():
            example = ENV_PATH.parent / "env.example"
            sys.stderr.write(
                f"The .env file does not exist. Bootstrap it with:\n  cp {example} {ENV_PATH}\n"
                "then edit configuration/.env to fill in the required values.\n"
            )
        hint = _ENV_HINTS.get(key)
        if hint:
            sys.stderr.write(hint + "\n")
        sys.stderr.write("See configuration/env.example for the full list of expected keys.\n\n")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = _required("SECRET_KEY")


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = _required("ALLOWED_HOSTS", cast=Csv())


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_admin_logs",
    "colorfield",
    "django_extensions",
    "stats",
    "webapp",
    "crawler",
    "network",
    "runner",
    "events",
    "rest_framework",
    "backoffice",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["backoffice.api.permissions.BackofficePermission"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "webapp_engine.middleware.WebAccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "webapp_engine.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "webapp.context_processors.web_access",
            ],
        },
    },
]

WSGI_APPLICATION = "webapp_engine.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

_DB_ENGINE = config("DB_ENGINE", default="sqlite").strip().lower()

if _DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _required("DB_NAME"),
            "USER": config("DB_USER", default=""),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }
elif _DB_ENGINE in ("mysql", "mariadb"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": _required("DB_NAME"),
            "USER": config("DB_USER", default=""),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }
elif _DB_ENGINE == "oracle":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.oracle",
            "NAME": _required("DB_NAME"),
            "USER": config("DB_USER", default=""),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="1521"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / config("DB_NAME", default="db.sqlite3", cast=str),
            "OPTIONS": {
                # Busy-wait up to 30 s before raising OperationalError: database is locked.
                # WAL journal mode is activated via the connection_created signal in webapp/apps.py
                # so concurrent reads (runserver) don't block crawler writes.
                "timeout": 30,
            },
        }
    }


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = config("LANGUAGE_CODE", default="en-us", cast=str)
TIME_ZONE = config("TIME_ZONE", default="UTC", cast=str)
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"
# Project-wide static assets that don't belong to any specific app
# (favicon, README screenshots reused in templates, project logo).
STATICFILES_DIRS = [BASE_DIR / "webapp_engine" / "static"]
MEDIA_URL = "/media/"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Opt into Django 7.0's HTTPS default for the `urlize` template filter so
# bare-domain links rendered in post bodies and channel descriptions get
# `https://` prepended. Silences the RemovedInDjango70Warning.
URLIZE_ASSUME_HTTPS = True

DJANGO_ADMIN_LOGS_ENABLED = False


# ── Cache ─────────────────────────────────────────────────────────────────────
# File-based cache (rather than the default in-memory LocMemCache) so that the
# crawl_channels management-command process and the webserver process share
# the same cache — crawler-side invalidations must reach the page renderer.
# Tests use DummyCache so cached state can't leak between cases.

if _RUNNING_TESTS:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(BASE_DIR / "tmp" / "django-cache"),
        }
    }


# ── Telegram credentials (.env) ───────────────────────────────────────────────

TELEGRAM_API_ID = _required("TELEGRAM_API_ID")
TELEGRAM_API_HASH = _required("TELEGRAM_API_HASH")
TELEGRAM_PHONE_NUMBER = _required("TELEGRAM_PHONE_NUMBER")

# ── Crawler behaviour (configuration/.operations-crawl) ──────────────────────

TELEGRAM_CRAWLER_DOWNLOAD_IMAGES = _crawl.downloads.images
TELEGRAM_CRAWLER_DOWNLOAD_VIDEO = _crawl.downloads.video
TELEGRAM_CRAWLER_DOWNLOAD_AUDIO = _crawl.downloads.audio
TELEGRAM_CRAWLER_DOWNLOAD_STICKERS = _crawl.downloads.stickers
TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA = _crawl.downloads.other_media

# ── Telegram client tuning (.env) ─────────────────────────────────────────────
# Connection / floodwait knobs for the Telethon client. These are deployment
# infrastructure, not per-run analysis options, and live alongside the API
# credentials above.
TELEGRAM_SESSION_NAME = config("TELEGRAM_SESSION_NAME", default="anon", cast=str)
TELEGRAM_CONNECTION_RETRIES = config("TELEGRAM_CONNECTION_RETRIES", default=10, cast=int)
TELEGRAM_RETRY_DELAY = config("TELEGRAM_RETRY_DELAY", default=5, cast=int)
TELEGRAM_FLOOD_SLEEP_THRESHOLD = config("TELEGRAM_FLOOD_SLEEP_THRESHOLD", default=60, cast=int)
IGNORE_FLOODWAIT = config("TELEGRAM_IGNORE_FLOODWAIT", default=True, cast=bool)
TELEGRAM_FLOODWAIT_SLEEP_SECONDS = config("TELEGRAM_FLOODWAIT_SLEEP_SECONDS", default=900, cast=int)
TELEGRAM_CRAWLER_GRACE_TIME = config("TELEGRAM_CRAWLER_GRACE_TIME", default=1, cast=int)

# ── Access control (.env) ─────────────────────────────────────────────────────
# The project title (and its description/criteria/notes) now lives in the DB,
# editable at Manage › Project (webapp.models.Project); it is no longer an
# environment variable.

# `python-decouple` does not strip inline `#` comments from env-var values,
# so defensively drop them: a user `.env` that copies env.example's format
# `WEB_ACCESS=ALL  # …` would otherwise produce a value like "ALL  # …" that
# matches none of the modes and silently flips the middleware into PROTECTED.
WEB_ACCESS = config("WEB_ACCESS", default="ALL", cast=str).split("#", 1)[0].strip().upper()

# ── Network and analysis options (configuration/.operations-structural) ──────

DEFAULT_CHANNEL_TYPES: list[str] = [t.strip().upper() for t in _crawl.scope.channel_types if str(t).strip()]

DEAD_LEAVES_COLOR = _structural.graph.dead_leaves_color
# Legacy shim: a stale ``community_palette = "ORGANIZATION"`` value (the old
# default, which meant "use Organization colours for ORG, vaporwave reversed
# elsewhere") is silently translated to the explicit pair below. The TOML file
# itself is not rewritten — analysts can update it on their next Save-as-defaults.
_raw_community_palette = _structural.graph.community_palette
if _raw_community_palette == "ORGANIZATION":
    COMMUNITY_PALETTE = "vaporwave"
    COMMUNITY_PALETTE_REVERSED = True
else:
    COMMUNITY_PALETTE = _raw_community_palette
    COMMUNITY_PALETTE_REVERSED = getattr(_structural.graph, "community_palette_reversed", True)
GRAPH_OUTPUT_DIR = _structural.graph.output_dir

# ── Crawl Channels defaults (configuration/.operations-crawl) ────────────────

CRAWL_GET_CHANNELS_INFO = _crawl.channels.get_channels_info
CRAWL_UPDATE_TYPE_EXCLUDED_INFO = _crawl.channels.update_type_excluded_info
CRAWL_MINE_ABOUT_TEXTS = _crawl.channels.mine_about_texts
CRAWL_FETCH_RECOMMENDED = _crawl.channels.fetch_recommended
CRAWL_RETRY_LOST_AND_PRIVATE = _crawl.channels.retry_lost_and_private
CRAWL_GET_NEW_MESSAGES = _crawl.messages.get_new_messages
CRAWL_FETCH_REPLIES = _crawl.messages.fetch_replies
CRAWL_REFRESH_MESSAGES_STATS = _crawl.messages.refresh_messages_stats
CRAWL_FIX_HOLES = _crawl.messages.fix_holes
CRAWL_FIX_MISSING_MEDIA = _crawl.messages.fix_missing_media
CRAWL_RETRY_LOST_MESSAGES = _crawl.messages.retry_lost_messages
CRAWL_RETRY_REFERENCES = _crawl.messages.retry_references
CRAWL_FORCE_RETRY_UNRESOLVED_REFERENCES = _crawl.messages.force_retry_unresolved_references
CRAWL_IN_DEGREES = _crawl.degrees.in_degrees
CRAWL_OUT_DEGREES = _crawl.degrees.out_degrees

# ── Structural Analysis defaults (configuration/.operations-structural) ──────

SA_OUTPUT_GRAPH = _structural.outputs.graph
SA_OUTPUT_3DGRAPH = _structural.outputs.graph_3d
SA_OUTPUT_HTML = _structural.outputs.html
SA_OUTPUT_XLSX = _structural.outputs.xlsx
SA_OUTPUT_GEXF = _structural.outputs.gexf
SA_OUTPUT_GRAPHML = _structural.outputs.graphml
SA_OUTPUT_CSV = _structural.outputs.csv
SA_SEO = _structural.outputs.seo
SA_VERTICAL_LAYOUT = _structural.outputs.vertical_layout
SA_FA2_ITERATIONS = _structural.computation.fa2_iterations
SA_LAYOUTS_2D = ",".join(_structural.layouts.layouts_2d)
SA_LAYOUTS_3D = ",".join(_structural.layouts.layouts_3d)
SA_MEASURES = ",".join(_structural.measures.selected)
SA_COMMUNITY_STRATEGIES = ",".join(_structural.communities.strategies)
SA_NETWORK_STAT_GROUPS = ",".join(_structural.network_stats.groups)
SA_INCLUDE_MENTIONS = _structural.edges.include_mentions
SA_INCLUDE_SELF_REFERENCES = _structural.edges.include_self_references
SA_EDGE_WEIGHT_STRATEGY = _structural.edges.weight_strategy
SA_DIFFUSION_WINDOW = _structural.computation.diffusion_window
SA_DRAW_DEAD_LEAVES = _structural.outputs.draw_dead_leaves
SA_STRUCTURAL_SIMILARITY = _structural.outputs.structural_similarity
SA_BEHAVIOURAL_EQUIVALENCE = _structural.outputs.behavioural_equivalence
SA_CONSENSUS_MATRIX = _structural.outputs.consensus_matrix
# CPM resolution moved into the per-instance community-strategy tokens (v0.25).
SA_COMMUNITY_DISTRIBUTION_THRESHOLD = _structural.computation.community_distribution_threshold
SA_INCLUDE_LOST = _structural.scope.include_lost
SA_INCLUDE_PRIVATE = _structural.scope.include_private
SA_TIMELINE_STEP = _structural.outputs.timeline_step
SA_VACANCY_MEASURES = ",".join(_structural.vacancy.measures)
SA_VACANCY_MONTHS_BEFORE = _structural.vacancy.months_before
SA_VACANCY_MONTHS_AFTER = _structural.vacancy.months_after
SA_VACANCY_MAX_CANDIDATES = _structural.vacancy.max_candidates
# Derived: robustness runs iff at least one strategy is configured. A separate
# file-level "enabled" key would drift from the strategy list (no separate
# enable knob in the Operations panel).
SA_ROBUSTNESS = bool(_structural.robustness.strategies)
SA_ROBUSTNESS_ALPHA = _structural.robustness.alpha
SA_ROBUSTNESS_STRATEGIES = ",".join(_structural.robustness.strategies)
SA_ROBUSTNESS_RUNS = _structural.robustness.runs
SA_ROBUSTNESS_NULL = _structural.robustness.null
SA_ROBUSTNESS_SEED = _structural.robustness.seed
SA_ROBUSTNESS_SAMPLE = _structural.robustness.sample
SA_INTEREST_STRUCTURAL = _structural.interest.structural
SA_INTEREST_WINDOW_DAYS = _structural.interest.window_days
SA_INTEREST_INCLUDE_MENTIONS = _structural.interest.include_mentions

# ── System constants (.system — managed by project, do not edit) ─────────────

APP_VERSION = _sys("APP_VERSION", default="0.19")
REPOSITORY_URL = _sys("REPOSITORY_URL", default="https://github.com/giovabal/pulpit")

# ─────────────────────────────────────────────────────────────────────────────

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
