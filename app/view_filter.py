EFFECTIVE_VIEW_SECONDS = 15
READING_HEARTBEAT_SECONDS = 15
MAX_READING_SECONDS = 30 * 60

BOT_USER_AGENT_KEYWORDS = (
    "bingbot",
    "msnbot",
    "adidxbot",
    "googlebot",
    "baiduspider",
    "bytespider",
    "yandexbot",
    "ahrefsbot",
    "semrushbot",
    "mj12bot",
    "dotbot",
    "petalbot",
    "gptbot",
    "claudebot",
    "amazonbot",
    "facebookexternalhit",
    "curl/",
    "wget/",
    "python-requests",
    "go-http-client",
    "headlesschrome",
)


def is_crawler_user_agent(user_agent):
    user_agent = (user_agent or "").strip().lower()
    if not user_agent:
        return True

    return any(keyword in user_agent for keyword in BOT_USER_AGENT_KEYWORDS)


def normalize_reading_seconds(value):
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return 0

    if seconds < 0:
        return 0

    return min(seconds, MAX_READING_SECONDS)


def is_effective_reading_seconds(value):
    return normalize_reading_seconds(value) >= EFFECTIVE_VIEW_SECONDS
