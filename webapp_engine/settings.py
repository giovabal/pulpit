import warnings
from pathlib import Path

from decouple import Config, Csv, RepositoryEnv, config

# Telethon calls the deprecated asyncio.get_event_loop() during initialisation
# when no loop is running yet (Python 3.12+). The warning is attributed to
# whichever frame asyncio's stacklevel resolves to, so we match on message +
# category only — the text is specific enough to avoid false positives.
warnings.filterwarnings(
    "ignore",
    message="There is no current event loop",
    category=DeprecationWarning,
)


def optional_int(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"none", ""}:
        return None
    return int(value)


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

MEDIA_ROOT_DIRNAME = "media"
MEDIA_ROOT = BASE_DIR / MEDIA_ROOT_DIRNAME


# ── Secondary config files ────────────────────────────────────────────────────
# config()  → AutoConfig: reads .env + os.environ (credentials, deployment)
# _ana(...) → .analysis-defaults (crawler behaviour, graph options)
# _sys(...) → .system-options   (version, repo URL — managed by project)


class _EmptyRepository:
    """Fallback repository that contains no keys — used when a config file is absent."""

    def __contains__(self, key: str) -> bool:
        return False

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)


_ANALYSIS_PATH = BASE_DIR / ".analysis-defaults"
_ana = Config(RepositoryEnv(str(_ANALYSIS_PATH)) if _ANALYSIS_PATH.exists() else _EmptyRepository())

_SYSTEM_PATH = BASE_DIR / ".system-options"
_sys = Config(RepositoryEnv(str(_SYSTEM_PATH)) if _SYSTEM_PATH.exists() else _EmptyRepository())

# ─────────────────────────────────────────────────────────────────────────────

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("SECRET_KEY", cast=str)


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())


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
            "NAME": config("DB_NAME", cast=str),
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
            "NAME": config("DB_NAME", cast=str),
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
            "NAME": config("DB_NAME", cast=str),
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

STATIC_URL = "static/"
MEDIA_URL = "media/"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DJANGO_ADMIN_LOGS_ENABLED = False


# ── Telegram credentials (.env) ───────────────────────────────────────────────

TELEGRAM_API_ID = config("TELEGRAM_API_ID", cast=str)
TELEGRAM_API_HASH = config("TELEGRAM_API_HASH", cast=str)
TELEGRAM_PHONE_NUMBER = config("TELEGRAM_PHONE_NUMBER", cast=str)

# ── Crawler behaviour (.analysis-defaults) ────────────────────────────────────

TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL = _ana(
    "TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL", default=100, cast=optional_int
)
TELEGRAM_CRAWLER_DOWNLOAD_IMAGES = _ana("TELEGRAM_CRAWLER_DOWNLOAD_IMAGES", default=False, cast=bool)
TELEGRAM_CRAWLER_DOWNLOAD_VIDEO = _ana("TELEGRAM_CRAWLER_DOWNLOAD_VIDEO", default=False, cast=bool)
TELEGRAM_CRAWLER_DOWNLOAD_AUDIO = _ana("TELEGRAM_CRAWLER_DOWNLOAD_AUDIO", default=False, cast=bool)
TELEGRAM_CRAWLER_DOWNLOAD_STICKERS = _ana("TELEGRAM_CRAWLER_DOWNLOAD_STICKERS", default=False, cast=bool)
TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA = _ana("TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA", default=False, cast=bool)
TELEGRAM_CRAWLER_GRACE_TIME = _ana("TELEGRAM_CRAWLER_GRACE_TIME", default=1, cast=int)
TELEGRAM_CONNECTION_RETRIES = _ana("TELEGRAM_CONNECTION_RETRIES", default=10, cast=int)
TELEGRAM_RETRY_DELAY = _ana("TELEGRAM_RETRY_DELAY", default=5, cast=int)
TELEGRAM_FLOOD_SLEEP_THRESHOLD = _ana("TELEGRAM_FLOOD_SLEEP_THRESHOLD", default=60, cast=int)
IGNORE_FLOODWAIT = _ana("IGNORE_FLOODWAIT", default=True, cast=bool)
TELEGRAM_FLOODWAIT_SLEEP_SECONDS = _ana("TELEGRAM_FLOODWAIT_SLEEP_SECONDS", default=900, cast=int)
TELEGRAM_SESSION_NAME = _ana("TELEGRAM_SESSION_NAME", default="anon", cast=str)

# ── Project identity (.env) ───────────────────────────────────────────────────

PROJECT_TITLE = config("PROJECT_TITLE", default="Pulpit project", cast=str)
WEB_ACCESS = config("WEB_ACCESS", default="ALL", cast=str).upper()

# ── Network and analysis options (.analysis-defaults) ─────────────────────────

REVERSED_EDGES = _ana("REVERSED_EDGES", default=True, cast=bool)

DEFAULT_CHANNEL_TYPES: list[str] = [
    t.strip().upper() for t in _ana("DEFAULT_CHANNEL_TYPES", default="CHANNEL", cast=str).split(",") if t.strip()
]

DEAD_LEAVES_COLOR = _ana("DEAD_LEAVES_COLOR", default="#596a64", cast=str)
COMMUNITY_PALETTE = _ana("COMMUNITY_PALETTE", default="ORGANIZATION", cast=str)
GRAPH_OUTPUT_DIR = _ana("GRAPH_OUTPUT_DIR", default="graph", cast=str)

# ── Crawl Channels defaults (.analysis-defaults) ─────────────────────────────

CRAWL_GET_CHANNELS_INFO = _ana("CRAWL_GET_CHANNELS_INFO", default=False, cast=bool)
CRAWL_UPDATE_TYPE_EXCLUDED_INFO = _ana("CRAWL_UPDATE_TYPE_EXCLUDED_INFO", default=False, cast=bool)
CRAWL_MINE_ABOUT_TEXTS = _ana("CRAWL_MINE_ABOUT_TEXTS", default=False, cast=bool)
CRAWL_FETCH_RECOMMENDED = _ana("CRAWL_FETCH_RECOMMENDED", default=False, cast=bool)
CRAWL_RETRY_LOST_AND_PRIVATE = _ana("CRAWL_RETRY_LOST_AND_PRIVATE", default=False, cast=bool)
CRAWL_GET_NEW_MESSAGES = _ana("CRAWL_GET_NEW_MESSAGES", default=False, cast=bool)
CRAWL_FETCH_REPLIES = _ana("CRAWL_FETCH_REPLIES", default=False, cast=bool)
CRAWL_REFRESH_MESSAGES_STATS = _ana("CRAWL_REFRESH_MESSAGES_STATS", default=False, cast=bool)
CRAWL_FIXHOLES = _ana("CRAWL_FIXHOLES", default=False, cast=bool)
CRAWL_FIX_MISSING_MEDIA = _ana("CRAWL_FIX_MISSING_MEDIA", default=False, cast=bool)
CRAWL_RETRY_LOST_MESSAGES = _ana("CRAWL_RETRY_LOST_MESSAGES", default=False, cast=bool)
CRAWL_RETRY_REFERENCES = _ana("CRAWL_RETRY_REFERENCES", default=False, cast=bool)
CRAWL_FORCE_RETRY_UNRESOLVED = _ana("CRAWL_FORCE_RETRY_UNRESOLVED", default=False, cast=bool)
CRAWL_IN_DEGREES = _ana("CRAWL_IN_DEGREES", default=False, cast=bool)
CRAWL_OUT_DEGREES = _ana("CRAWL_OUT_DEGREES", default=False, cast=bool)

# ── Structural Analysis defaults (.analysis-defaults) ─────────────────────────

SA_OUTPUT_GRAPH = _ana("SA_OUTPUT_GRAPH", default=False, cast=bool)
SA_OUTPUT_3DGRAPH = _ana("SA_OUTPUT_3DGRAPH", default=False, cast=bool)
SA_OUTPUT_HTML = _ana("SA_OUTPUT_HTML", default=False, cast=bool)
SA_OUTPUT_XLSX = _ana("SA_OUTPUT_XLSX", default=False, cast=bool)
SA_OUTPUT_GEXF = _ana("SA_OUTPUT_GEXF", default=False, cast=bool)
SA_OUTPUT_GRAPHML = _ana("SA_OUTPUT_GRAPHML", default=False, cast=bool)
SA_OUTPUT_CSV = _ana("SA_OUTPUT_CSV", default=False, cast=bool)
SA_SEO = _ana("SA_SEO", default=False, cast=bool)
SA_VERTICAL_LAYOUT = _ana("SA_VERTICAL_LAYOUT", default=False, cast=bool)
SA_FA2_ITERATIONS = _ana("SA_FA2_ITERATIONS", default=5000, cast=int)
SA_LAYOUTS_2D = _ana("SA_LAYOUTS_2D", default="FA2", cast=str)
SA_LAYOUTS_3D = _ana("SA_LAYOUTS_3D", default="FA2", cast=str)
SA_MEASURES = _ana("SA_MEASURES", default="PAGERANK", cast=str)
SA_COMMUNITY_STRATEGIES = _ana("SA_COMMUNITY_STRATEGIES", default="ORGANIZATION", cast=str)
SA_NETWORK_STAT_GROUPS = _ana("SA_NETWORK_STAT_GROUPS", default="ALL", cast=str)
SA_INCLUDE_MENTIONS = _ana("SA_INCLUDE_MENTIONS", default=True, cast=bool)
SA_INCLUDE_SELF_REFERENCES = _ana("SA_INCLUDE_SELF_REFERENCES", default=False, cast=bool)
SA_EDGE_WEIGHT_STRATEGY = _ana("SA_EDGE_WEIGHT_STRATEGY", default="PARTIAL_REFERENCES", cast=str)
SA_RECENCY_WEIGHTS = _ana("SA_RECENCY_WEIGHTS", default=None, cast=optional_int)
SA_SPREADING_RUNS = _ana("SA_SPREADING_RUNS", default=200, cast=int)
SA_DIFFUSION_WINDOW = _ana("SA_DIFFUSION_WINDOW", default=30, cast=int)
SA_DRAW_DEAD_LEAVES = _ana("SA_DRAW_DEAD_LEAVES", default=False, cast=bool)
SA_STRUCTURAL_SIMILARITY = _ana("SA_STRUCTURAL_SIMILARITY", default=False, cast=bool)
SA_CONSENSUS_MATRIX = _ana("SA_CONSENSUS_MATRIX", default=False, cast=bool)
SA_LEIDEN_COARSE_RESOLUTION = _ana("SA_LEIDEN_COARSE_RESOLUTION", default=0.01, cast=float)
SA_LEIDEN_FINE_RESOLUTION = _ana("SA_LEIDEN_FINE_RESOLUTION", default=0.05, cast=float)
SA_MCL_INFLATION = _ana("SA_MCL_INFLATION", default=2.0, cast=float)
SA_COMMUNITY_DISTRIBUTION_THRESHOLD = _ana("SA_COMMUNITY_DISTRIBUTION_THRESHOLD", default=10, cast=int)
SA_INCLUDE_LOST = _ana("SA_INCLUDE_LOST", default=False, cast=bool)
SA_INCLUDE_PRIVATE = _ana("SA_INCLUDE_PRIVATE", default=False, cast=bool)
SA_TIMELINE_STEP = _ana("SA_TIMELINE_STEP", default="none", cast=str)
SA_VACANCY_MEASURES = _ana("SA_VACANCY_MEASURES", default="", cast=str)
SA_VACANCY_MONTHS_BEFORE = _ana("SA_VACANCY_MONTHS_BEFORE", default=12, cast=int)
SA_VACANCY_MONTHS_AFTER = _ana("SA_VACANCY_MONTHS_AFTER", default=24, cast=int)
SA_VACANCY_MAX_CANDIDATES = _ana("SA_VACANCY_MAX_CANDIDATES", default=30, cast=int)
SA_VACANCY_PPR_ALPHA = _ana("SA_VACANCY_PPR_ALPHA", default=0.85, cast=float)

# ── System constants (.system-options — managed by project, do not edit) ──────

APP_VERSION = _sys("APP_VERSION", default="0.19")
REPOSITORY_URL = _sys("REPOSITORY_URL", default="https://github.com/giovabal/pulpit")

# ─────────────────────────────────────────────────────────────────────────────

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
