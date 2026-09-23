"""Shared diary date and location rules."""
from datetime import timedelta
from math import asin, cos, isfinite, radians, sin, sqrt

LOCATION_RETRY_METERS = 1000
EARTH_RADIUS_METERS = 6371008.8


def diary_date(now):
    # The entire 04:00 minute still belongs to the previous diary day.
    return (now - timedelta(hours=4, minutes=1)).date()


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _accuracy(location):
    accuracy = _finite((location or {}).get("accuracy_m"))
    return None if accuracy is None or accuracy < 0 else accuracy


def location_needs_retry(location):
    if not location or location.get("latitude") is None or location.get("longitude") is None:
        return True
    accuracy = _accuracy(location)
    return accuracy is None or accuracy > LOCATION_RETRY_METERS


def distance_meters(old, new):
    """Great-circle distance between two fixes, or None when either lacks coordinates."""
    points = []
    for location in (old, new):
        latitude = _finite((location or {}).get("latitude"))
        longitude = _finite((location or {}).get("longitude"))
        if latitude is None or longitude is None:
            return None
        points.append((radians(latitude), radians(longitude)))

    (old_latitude, old_longitude), (new_latitude, new_longitude) = points
    half_chord = (
        sin((new_latitude - old_latitude) / 2) ** 2
        + cos(old_latitude) * cos(new_latitude) * sin((new_longitude - old_longitude) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * asin(min(1.0, sqrt(half_chord)))


def locations_contradict(old, new):
    """True when two fixes are further apart than their own error radii can explain."""
    distance = distance_meters(old, new)
    if distance is None:
        return False
    tolerance = 0.0
    for location in (old, new):
        accuracy = _accuracy(location)
        tolerance += LOCATION_RETRY_METERS if accuracy is None else accuracy
    return distance > tolerance


def better_location(old, new):
    if not location_needs_retry(old) or not new.get("formatted_address"):
        return False
    accuracy = _accuracy(new)
    if accuracy is None:
        return False
    previous = _accuracy(old)
    if previous is None:
        return True
    # The stored fix is already untrusted, so a reading that cannot describe the same
    # place proves it wrong no matter what error radius either reading claims.
    return accuracy < previous or locations_contradict(old, new)
