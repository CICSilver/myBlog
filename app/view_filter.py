from functools import lru_cache
import ipaddress
import socket


EFFECTIVE_VIEW_SECONDS = 15
READING_HEARTBEAT_SECONDS = 15
MAX_READING_SECONDS = 30 * 60
ARTICLE_VIEW_MERGE_SECONDS = 30

DEFAULT_EXCLUDED_ARTICLE_VIEW_IPS = (
    ("114.221.164.47", "测试机"),
)

VERIFIED_CRAWLER_DNS_SUFFIXES = (
    ".search.msn.com",
)
VERIFIED_CRAWLER_IP_CANDIDATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "40.77.167.0/24",
        "157.55.39.0/24",
        "207.46.13.0/24",
    )
)

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


def is_loopback_ip(ip):
    ip_text = str(ip or "").strip()
    if not ip_text:
        return False

    if ip_text.lower() == "localhost" or ip_text.startswith("127."):
        return True

    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    if address.is_loopback:
        return True

    if address.version == 6 and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback

    return False


def normalize_ip_address(ip):
    ip_text = str(ip or "").strip()
    if not ip_text:
        return ""

    try:
        return str(ipaddress.ip_address(ip_text))
    except ValueError:
        return ""


def is_ip_in_set(ip, ip_set):
    ip_text = normalize_ip_address(ip)
    return bool(ip_text and ip_text in ip_set)


@lru_cache(maxsize=2048)
def is_verified_crawler_ip(ip):
    ip_text = str(ip or "").strip()
    if not ip_text:
        return False

    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    if not _is_verified_crawler_candidate_address(address):
        return False

    hostname = _resolve_reverse_hostname(ip_text)
    if not _has_verified_crawler_hostname(hostname):
        return False

    return address in _resolve_forward_addresses(hostname)


def _is_verified_crawler_candidate_address(address):
    return any(address in network for network in VERIFIED_CRAWLER_IP_CANDIDATE_NETWORKS)


def _has_verified_crawler_hostname(hostname):
    hostname = str(hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return False

    return any(
        hostname.endswith(suffix)
        for suffix in VERIFIED_CRAWLER_DNS_SUFFIXES
    )


def _resolve_reverse_hostname(ip):
    try:
        hostname, _aliases, _addresses = socket.gethostbyaddr(ip)
    except (OSError, socket.herror, socket.gaierror):
        return ""

    return hostname


def _resolve_forward_addresses(hostname):
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except (OSError, socket.gaierror):
        return set()

    addresses = set()
    for info in addrinfo:
        try:
            addresses.add(ipaddress.ip_address(info[4][0]))
        except (IndexError, ValueError):
            continue

    return addresses


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
