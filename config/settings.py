"""Django settings for TestDeck."""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "dashboard.middleware.JiraCredentialsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "dashboard.context_processors.jira_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Large HTML folder uploads (many pytest-html reports). Prefer Import ZIP for 40+ files.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(256 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(64 * 1024 * 1024))
)
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv("DATA_UPLOAD_MAX_NUMBER_FIELDS", "5000"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Jira / Xray integration
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://jira.silabs.com").rstrip("/")
JIRA_USERNAME = os.getenv("JIRA_USERNAME", "")
JIRA_PASSWORD = os.getenv("JIRA_PASSWORD", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SW_SQA_TE")
JIRA_TEST_PROJECT_KEY = os.getenv("JIRA_TEST_PROJECT_KEY", "SW_SQA_TC")
JIRA_VERIFY_SSL = os.getenv("JIRA_VERIFY_SSL", "true").lower() in {"1", "true", "yes", "on"}

# Silabs Xray issue type names (confirmed via /rest/api/2/project)
JIRA_ISSUE_TYPE_TEST_EXECUTION = os.getenv(
    "JIRA_ISSUE_TYPE_TEST_EXECUTION", "Xray Test Execution"
)
JIRA_ISSUE_TYPE_TEST_PLAN = os.getenv("JIRA_ISSUE_TYPE_TEST_PLAN", "Xray Test Plan")
JIRA_ISSUE_TYPE_TEST = os.getenv("JIRA_ISSUE_TYPE_TEST", "Xray Test")

# Failure-triage similar-bug search (read-only JQL).
# Primary pool (preferred / "apt"): Coex SQA bugs. Extra pool: SI91X, etc.
JIRA_SIMILAR_BUG_BASE_JQL = os.getenv(
    "JIRA_SIMILAR_BUG_BASE_JQL",
    (
        'project = "24367" AND issuetype = Bug AND '
        "reporter in (currentUser(), asthakur, lomayalu, "
        "membersOf(DL.Hyd-Coex-SQA))"
    ),
)
# Secondary pools (semicolon-separated JQLs). Surfed too; Coex still ranks higher.
JIRA_SIMILAR_BUG_EXTRA_JQL = os.getenv(
    "JIRA_SIMILAR_BUG_EXTRA_JQL",
    'project = SI91X AND issuetype in ("Bug", "Defect")',
)
JIRA_SIMILAR_BUG_CORPUS_LIMIT = int(
    os.getenv("JIRA_SIMILAR_BUG_CORPUS_LIMIT", "500")
)
JIRA_SIMILAR_BUG_EXTRA_CORPUS_LIMIT = int(
    os.getenv("JIRA_SIMILAR_BUG_EXTRA_CORPUS_LIMIT", "300")
)
# Legacy fallback when JIRA_SIMILAR_BUG_BASE_JQL is blank.
JIRA_BUG_PROJECT_KEYS = os.getenv(
    "JIRA_BUG_PROJECT_KEYS", "WIFI_BT_UTFHELP,SI91X"
)
JIRA_BUG_ISSUE_TYPES = os.getenv("JIRA_BUG_ISSUE_TYPES", "Bug,Defect")

# Jira *Test issue* fields from SWSQAT: Xray View Test Screen (not Test Run TRCFs).
XRAY_FIELD_MAP = {
    "test_repo_path": os.getenv("XRAY_TEST_REPO_PATH_FIELD", "customfield_30962"),
    "test_environments": os.getenv("XRAY_TEST_ENVIRONMENTS_FIELD", ""),
    "test_plan": os.getenv("XRAY_TEST_PLAN_FIELD", ""),
    "stack_name": os.getenv("XRAY_STACK_NAME_FIELD", "customfield_32353"),
    # Auto-detected by name if blank; set once known (plan Details: release_name).
    "release_name": os.getenv("XRAY_RELEASE_NAME_FIELD", ""),
    "feature_name": os.getenv("XRAY_FEATURE_NAME_FIELD", "customfield_32357"),
    "sub_feature_name": os.getenv("XRAY_SUB_FEATURE_NAME_FIELD", "customfield_32346"),
    "tech_area": os.getenv("XRAY_TECH_AREA_FIELD", "customfield_33453"),
    "testrail_section": os.getenv("XRAY_TESTRAIL_SECTION_FIELD", "customfield_33577"),
    "case_id": os.getenv("XRAY_CASE_ID_FIELD", "customfield_33571"),
    "test_area": os.getenv("XRAY_TEST_AREA_FIELD", "customfield_33578"),
    # Confirmed on jira.silabs.com (SWSQAT screen)
    "technology": os.getenv("XRAY_TECHNOLOGY_FIELD", "customfield_22640"),
    "test_src_map_id": os.getenv("XRAY_TEST_SRC_MAP_ID_FIELD", "customfield_32360"),
    # Test issue "References" (often RSCDEV epic/link), e.g. RSCDEV-23314
    "references": os.getenv("XRAY_REFERENCES_FIELD", "customfield_33347"),
}

# Numeric Xray Test Run Custom Field IDs (from Network: testRunValues&customFieldId=)
# Confirmed: Test_Execution_Method=18, Test Mode=19, Interface type=20, Host Platform=22
XRAY_TRCF_IDS = {
    "feature_name": os.getenv("XRAY_TRCF_FEATURE_NAME", ""),
    "sub_feature_name": os.getenv("XRAY_TRCF_SUB_FEATURE_NAME", ""),
    "jenkins_test_results_url": os.getenv("XRAY_TRCF_JENKINS_URL", ""),
    "evk_version": os.getenv("XRAY_TRCF_EVK_VERSION", ""),
    "host_platform": os.getenv("XRAY_TRCF_HOST_PLATFORM", "22"),
    "build_version": os.getenv("XRAY_TRCF_BUILD_VERSION", ""),
    "interface_type": os.getenv("XRAY_TRCF_INTERFACE_TYPE", "20"),
    "test_mode": os.getenv("XRAY_TRCF_TEST_MODE", "19"),
    "test_execution_method": os.getenv("XRAY_TRCF_TEST_EXECUTION_METHOD", "18"),
    "board_details": os.getenv("XRAY_TRCF_BOARD_DETAILS", ""),
    "measured_kpi_value": os.getenv("XRAY_TRCF_MEASURED_KPI", ""),
    "target_kpi_value": os.getenv("XRAY_TRCF_TARGET_KPI", ""),
}

# Optional defaults — leave blank so UI starts empty; user picks filters/plan/run.
DEFAULT_TECHNOLOGY = os.getenv("DEFAULT_TECHNOLOGY", "")
DEFAULT_STACK_NAME = os.getenv("DEFAULT_STACK_NAME", "")
DEFAULT_RELEASE_NAME = os.getenv("DEFAULT_RELEASE_NAME", "")
DEFAULT_PLAN_KEY = os.getenv("DEFAULT_PLAN_KEY", "")
# Footer credit (shown site-wide; not the Jira signed-in user)
SITE_CREDIT_NAME = os.getenv("SITE_CREDIT_NAME", "Teja Sree Jammulamadaka")
# Plan view uses a selected Test Execution for case status (not plan latestStatus)
PLAN_STATUS_FROM_EXECUTION = os.getenv("PLAN_STATUS_FROM_EXECUTION", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
XRAY_HARD_LIMIT = int(os.getenv("XRAY_HARD_LIMIT", "5000"))
UI_PAGE_SIZE = int(os.getenv("UI_PAGE_SIZE", "50"))

# Cache expensive Jira/Xray calls (speeds up reloads significantly)
JIRA_CACHE_SECONDS = int(os.getenv("JIRA_CACHE_SECONDS", "300"))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "testdeck",
        "TIMEOUT": JIRA_CACHE_SECONDS,
    }
}
