from __future__ import annotations

import json
import os
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
DEPLOYMENT_PATH = Path(
    os.environ.get("PRODUCTIVITY_DEPLOYMENT_CONFIG", PROJECT_ROOT / "config" / "deployment.json")
)

with DEPLOYMENT_PATH.open("r", encoding="utf-8-sig") as handle:
    DEPLOYMENT = json.load(handle)

ENVIRONMENT = DEPLOYMENT["environment"]
AI_ENABLED = bool(DEPLOYMENT["ai_enabled"])
if AI_ENABLED:
    raise RuntimeError("AI/model execution is disabled for this release.")
DEBUG = ENVIRONMENT == "development"

secret_path = Path(
    os.environ.get(
        "PRODUCTIVITY_DJANGO_SECRET_FILE",
        PROJECT_ROOT / "runtime" / "secrets" / "django_secret.txt",
    )
)
if not secret_path.is_file():
    raise RuntimeError(f"Django secret file is missing: {secret_path}")
SECRET_KEY = secret_path.read_text(encoding="ascii").strip()
if len(SECRET_KEY) < 50:
    raise RuntimeError("Django secret is unexpectedly short")

private_base_url = DEPLOYMENT.get("private_base_url")
if ENVIRONMENT == "pilot" and not private_base_url:
    raise RuntimeError("Pilot configuration requires private_base_url")
if ENVIRONMENT == "pilot" and not DEPLOYMENT.get("allowed_client_cidrs"):
    raise RuntimeError("Pilot configuration requires allowed_client_cidrs")
if ENVIRONMENT == "pilot" and not DEPLOYMENT.get("manager_user_id"):
    raise RuntimeError("Pilot configuration requires manager_user_id")
if ENVIRONMENT == "pilot" and not DEPLOYMENT.get("backup_target"):
    raise RuntimeError("Pilot configuration requires backup_target")

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS: list[str] = []

lan_host = os.environ.get("PRODUCTIVITY_LAN_HOST", "").strip()
if lan_host:
    if ENVIRONMENT != "development":
        raise RuntimeError("PRODUCTIVITY_LAN_HOST is only permitted in development")
    address = ip_address(lan_host)
    if not address.is_private:
        raise RuntimeError("PRODUCTIVITY_LAN_HOST must be a private IPv4 or IPv6 address")
    ALLOWED_HOSTS.append(lan_host)
    CSRF_TRUSTED_ORIGINS.extend(
        [
            f"http://{lan_host}:5173",
            f"http://{lan_host}:8080",
        ]
    )

if private_base_url:
    parsed = urlparse(private_base_url)
    if not parsed.hostname or parsed.scheme != "https":
        raise RuntimeError("private_base_url must be an https URL with a hostname")
    ALLOWED_HOSTS.append(parsed.hostname)
    CSRF_TRUSTED_ORIGINS.append(f"{parsed.scheme}://{parsed.netloc}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "core",
    "accounts",
    "boards",
    "workitems",
    "schedules",
    "notifications",
    "reports",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.SessionGenerationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]
ROOT_URLCONF = "productivity.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "productivity.wsgi.application"

db_password_file = os.environ.get("PRODUCTIVITY_DB_PASSWORD_FILE")
if not db_password_file:
    local_db_secret = PROJECT_ROOT / "runtime" / "secrets" / "postgres_app_secret.txt"
    if local_db_secret.is_file():
        db_password_file = str(local_db_secret)

db_password = ""
if db_password_file:
    p = Path(db_password_file)
    if not p.is_file():
        raise RuntimeError("PRODUCTIVITY_DB_PASSWORD_FILE does not exist")
    db_password = p.read_text(encoding="utf-8").strip()

db_name = {
    "development": "productivity_dev",
    "test": "productivity_test",
    "pilot": "productivity_pilot",
}[ENVIRONMENT]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PRODUCTIVITY_DB_NAME", db_name),
        "USER": os.environ.get("PRODUCTIVITY_DB_USER", "productivity_app"),
        "PASSWORD": db_password,
        "HOST": os.environ.get("PRODUCTIVITY_DB_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("PRODUCTIVITY_DB_PORT", "5432")),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
        "TEST": {"NAME": "productivity_test"},
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = DEPLOYMENT["timezone"]
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = PROJECT_ROOT / "runtime" / "static"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_NAME = "emega_productivity_sessionid"
CSRF_COOKIE_NAME = "emega_productivity_csrftoken"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
SESSION_COOKIE_PATH = "/"
CSRF_COOKIE_PATH = "/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = ENVIRONMENT == "pilot"
# Persistent login with bounded risk:
# - 30-day sliding idle window (renewed while actively used)
# - 90-day absolute lifetime enforced by SessionGenerationMiddleware
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
PRODUCTIVITY_SESSION_ABSOLUTE_AGE = 90 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = ENVIRONMENT == "pilot"
SECURE_SSL_REDIRECT = ENVIRONMENT == "pilot"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if ENVIRONMENT == "pilot" else None
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "core.api.exception_handler",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "eMEGA Productivity API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "core.logging.RedactingJsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "productivity": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

LOGIN_URL = "/api/v1/session/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"
