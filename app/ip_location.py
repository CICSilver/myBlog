import ipaddress
import os
from threading import RLock


UNKNOWN_LOCATION = "未知"
LOCAL_NETWORK_LOCATION = "本地/内网"

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "ip2region_v4.xdb")
_searcher = None
_searcher_loaded = False
_searcher_lock = RLock()
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "0.0.0.0/8",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "::/128",
    )
)


def resolve_ip_location(ip):
    address = _parse_ip_address(ip)
    if address is None:
        return _unknown_location()

    if _is_local_network_address(address):
        return _local_network_location()

    if address.version != 4:
        return _unknown_location()

    searcher = _get_searcher()
    if searcher is None:
        return _unknown_location()

    try:
        region = searcher.search(str(address))
    except Exception:
        return _unknown_location()

    return _location_from_region(region)


def with_ip_location_defaults(view):
    view_with_defaults = dict(view)
    for key, value in _unknown_location().items():
        view_with_defaults.setdefault(key, value)
    return view_with_defaults


def _parse_ip_address(ip):
    if not ip:
        return None

    try:
        return ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None


def _is_local_network_address(address):
    return any(address in network for network in _LOCAL_NETWORKS)


def _get_searcher():
    global _searcher
    global _searcher_loaded

    if _searcher_loaded:
        return _searcher

    with _searcher_lock:
        if _searcher_loaded:
            return _searcher

        _searcher_loaded = True

        try:
            import ip2region.searcher as xdb
            import ip2region.util as util

            if not os.path.exists(_DATA_PATH):
                return None

            util.verify_from_file(_DATA_PATH)
            content = util.load_content_from_file(_DATA_PATH)
            _searcher = xdb.new_with_buffer(util.IPv4, content)
        except Exception:
            _searcher = None

        return _searcher


def _location_from_region(region):
    if not region:
        return _unknown_location()

    parts = str(region).split("|")
    parts = (parts + ["", "", "", "", ""])[:5]
    country, province, city, isp, country_code = [_clean_part(part) for part in parts]

    if not country or country.lower() == "reserved":
        return _unknown_location()

    location_parts = [part for part in (country, province, city, isp) if part]
    if not location_parts:
        return _unknown_location()

    return {
        "ip_location": " / ".join(location_parts),
        "ip_country": country,
        "ip_region": province,
        "ip_city": city,
        "ip_isp": isp,
        "ip_country_code": country_code,
    }


def _clean_part(value):
    value = str(value or "").strip()
    if not value or value == "0":
        return ""
    return value


def _unknown_location():
    return {
        "ip_location": UNKNOWN_LOCATION,
        "ip_country": "",
        "ip_region": "",
        "ip_city": "",
        "ip_isp": "",
        "ip_country_code": "",
    }


def _local_network_location():
    return {
        "ip_location": LOCAL_NETWORK_LOCATION,
        "ip_country": LOCAL_NETWORK_LOCATION,
        "ip_region": "",
        "ip_city": "",
        "ip_isp": "",
        "ip_country_code": "",
    }
