import warnings
from pathlib import Path

from decouple import Csv, config

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
    "PAGE_SIZE": 50,
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


TELEGRAM_API_ID = config("TELEGRAM_API_ID", cast=str)
TELEGRAM_API_HASH = config("TELEGRAM_API_HASH", cast=str)
TELEGRAM_PHONE_NUMBER = config("TELEGRAM_PHONE_NUMBER", cast=str)
TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL = config(
    "TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL", default=100, cast=optional_int
)
TELEGRAM_CRAWLER_DOWNLOAD_IMAGES = config("TELEGRAM_CRAWLER_DOWNLOAD_IMAGES", default=False, cast=bool)
TELEGRAM_CRAWLER_DOWNLOAD_VIDEO = config("TELEGRAM_CRAWLER_DOWNLOAD_VIDEO", default=False, cast=bool)
TELEGRAM_CRAWLER_GRACE_TIME = config("TELEGRAM_CRAWLER_GRACE_TIME", default=1, cast=int)
TELEGRAM_CONNECTION_RETRIES = config("TELEGRAM_CONNECTION_RETRIES", default=10, cast=int)
TELEGRAM_RETRY_DELAY = config("TELEGRAM_RETRY_DELAY", default=5, cast=int)
TELEGRAM_FLOOD_SLEEP_THRESHOLD = config("TELEGRAM_FLOOD_SLEEP_THRESHOLD", default=60, cast=int)
IGNORE_FLOODWAIT = config("IGNORE_FLOODWAIT", default=True, cast=bool)
TELEGRAM_FLOODWAIT_SLEEP_SECONDS = config("TELEGRAM_FLOODWAIT_SLEEP_SECONDS", default=900, cast=int)
TELEGRAM_SESSION_NAME = config("TELEGRAM_SESSION_NAME", default="anon", cast=str)

PROJECT_TITLE = config("PROJECT_TITLE", default="Pulpit project", cast=str)

REVERSED_EDGES = config("REVERSED_EDGES", default=True, cast=bool)

DEFAULT_CHANNEL_TYPES: list[str] = [
    t.strip().upper() for t in config("DEFAULT_CHANNEL_TYPES", default="CHANNEL", cast=str).split(",") if t.strip()
]

DEAD_LEAVES_COLOR = config("DEAD_LEAVES_COLOR", default="#596a64", cast=str)

COMMUNITY_PALETTE = config("COMMUNITY_PALETTE", default="ORGANIZATION", cast=str)

GRAPH_OUTPUT_DIR = config("GRAPH_OUTPUT_DIR", default="graph", cast=str)

WEB_ACCESS = config("WEB_ACCESS", default="ALL", cast=str).upper()

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
