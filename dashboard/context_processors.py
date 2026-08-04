from django.conf import settings

from .credentials import credentials_configured, get_active_credentials


def jira_settings(request):
    if "technology" in request.GET:
        tech = request.GET.get("technology") or ""
    else:
        tech = settings.DEFAULT_TECHNOLOGY or ""
    if tech and "BLE" in tech.upper() and "WLAN" in tech.upper() and "+" not in tech:
        collapsed = " ".join(tech.split())
        if collapsed.upper() in {"WLAN BLE", "WLAN  BLE"}:
            tech = "WLAN + BLE"
    elif tech:
        tech = " ".join(tech.split())

    if "stack" in request.GET or "stack_name" in request.GET:
        stack = request.GET.get("stack") or request.GET.get("stack_name") or ""
    else:
        stack = getattr(settings, "DEFAULT_STACK_NAME", "") or ""
    if stack:
        stack = " ".join(str(stack).split())

    if "release" in request.GET or "release_name" in request.GET:
        release = request.GET.get("release") or request.GET.get("release_name") or ""
    else:
        release = getattr(settings, "DEFAULT_RELEASE_NAME", "") or ""
    if release:
        release = " ".join(str(release).split())

    creds = get_active_credentials()
    display_name = (
        request.session.get("jira_display_name")
        or request.session.get("jira_username")
        or settings.JIRA_USERNAME
        or ""
    )

    # Technology options: prefer cached Jira list; fall back to seeds.
    technology_options: list[str] = []
    try:
        from django.core.cache import cache

        cached = cache.get("technology_options_v1")
        if isinstance(cached, list) and cached:
            technology_options = cached
    except Exception:
        technology_options = []
    if not technology_options:
        from .services import SEED_TECHNOLOGIES

        technology_options = list(SEED_TECHNOLOGIES)
        if credentials_configured():
            try:
                from .services import get_service

                technology_options = get_service().list_technology_options()
            except Exception:
                pass

    stack_options: list[str] = []
    try:
        from django.core.cache import cache

        cached_stacks = cache.get("stack_name_options_v1")
        if isinstance(cached_stacks, list) and cached_stacks:
            stack_options = cached_stacks
    except Exception:
        stack_options = []
    if not stack_options:
        from .services import SEED_STACK_NAMES

        stack_options = list(SEED_STACK_NAMES)
        if credentials_configured():
            try:
                from .services import get_service

                stack_options = get_service().list_stack_name_options()
            except Exception:
                pass

    release_options: list[str] = []
    try:
        from django.core.cache import cache

        cached_releases = cache.get("release_name_options_v1")
        if isinstance(cached_releases, list) and cached_releases:
            release_options = cached_releases
    except Exception:
        release_options = []
    if not release_options:
        from .services import SEED_RELEASE_NAMES

        release_options = list(SEED_RELEASE_NAMES)
        if credentials_configured():
            try:
                from .services import get_service

                release_options = get_service().list_release_name_options()
            except Exception:
                pass

    return {
        "JIRA_BASE_URL": creds.get("base_url") or settings.JIRA_BASE_URL,
        "JIRA_PROJECT_KEY": settings.JIRA_PROJECT_KEY,
        "JIRA_TEST_PROJECT_KEY": settings.JIRA_TEST_PROJECT_KEY,
        "JIRA_CONFIGURED": credentials_configured(),
        "JIRA_USERNAME_DISPLAY": request.session.get("jira_username")
        or settings.JIRA_USERNAME
        or "",
        "JIRA_AUTHOR_DISPLAY": display_name,
        "DEFAULT_TECHNOLOGY": settings.DEFAULT_TECHNOLOGY,
        "DEFAULT_STACK_NAME": getattr(settings, "DEFAULT_STACK_NAME", "") or "",
        "DEFAULT_RELEASE_NAME": getattr(settings, "DEFAULT_RELEASE_NAME", "") or "",
        "DEFAULT_PLAN_KEY": settings.DEFAULT_PLAN_KEY,
        "SITE_CREDIT_NAME": settings.SITE_CREDIT_NAME,
        "ACTIVE_TECHNOLOGY": tech,
        "ACTIVE_STACK_NAME": stack,
        "ACTIVE_RELEASE_NAME": release,
        "TECHNOLOGY_OPTIONS": technology_options,
        "STACK_OPTIONS": stack_options,
        "RELEASE_OPTIONS": release_options,
    }
