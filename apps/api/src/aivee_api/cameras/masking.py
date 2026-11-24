"""Camera passwords stay in the database and the device's retained config, never in a response.

The dashboard stores a camera's full source URL, password included, because the edge needs it.
Every response (list, get, create, update, audit) shows it masked:

    rtsp://admin:s3cr3t@192.168.1.21:554/stream2 → rtsp://admin:***@192.168.1.21:554/stream2

Query parameters that look like credentials (`password=`, `token=`, …) are masked the same way.
A user name alone is not masked. An edit that sends the masked value back (the dashboard keeps
the address and asks only for a new password) means "keep the stored one": `restore_masked`
puts the stored password back, even when the host, user or path changed.
"""

import re
from urllib.parse import urlsplit

MASK = "***"

_USERINFO = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/?#]*)@")
_SECRET_PARAM = re.compile(
    r"(?P<key>[?&;](?:pass(?:word)?|pwd|token|key|secret|auth|sig(?:nature)?)=)(?P<value>[^&#;]*)",
    re.IGNORECASE,
)


class MaskedWithoutPassword(ValueError):
    """The masked value was sent back, but there is no stored password to keep."""


def _password(source: str) -> str | None:
    m = _USERINFO.match(source)
    if m is None:
        return None
    _user, sep, password = m.group("userinfo").partition(":")
    return password if sep else None


def _params(source: str) -> dict[str, str]:
    return {p.group("key").lower(): p.group("value") for p in _SECRET_PARAM.finditer(source)}


def mask_source(source: str) -> str:
    """`source` with its password and secret query values replaced by `***`."""
    text = source
    m = _USERINFO.match(text)
    if m is not None:
        user, sep, _password = m.group("userinfo").partition(":")
        if sep:
            text = f"{m.group('scheme')}{user}:{MASK}@{text[m.end() :]}"
    return _SECRET_PARAM.sub(lambda p: p.group("key") + MASK, text)


def is_masked(source: str) -> bool:
    """`source` carries `***` where a password goes."""
    return _password(source) == MASK or MASK in _params(source).values()


def restore_masked(source: str, stored: str) -> str:
    """`source` with every `***` replaced by the stored source's secret in the same place.
    Raises `MaskedWithoutPassword` when the stored source has none there."""
    text = source
    m = _USERINFO.match(text)
    if m is not None:
        user, sep, password = m.group("userinfo").partition(":")
        if sep and password == MASK:
            kept = _password(stored)
            if not kept:
                raise MaskedWithoutPassword("no stored password to keep")
            text = f"{m.group('scheme')}{user}:{kept}@{text[m.end() :]}"
    stored_params = _params(stored)

    def keep(p: re.Match[str]) -> str:
        if p.group("value") != MASK:
            return p.group(0)
        kept = stored_params.get(p.group("key").lower())
        if not kept:
            raise MaskedWithoutPassword("no stored secret to keep")
        return p.group("key") + kept

    return _SECRET_PARAM.sub(keep, text)


def url_host(source: str) -> str | None:
    """The host of a URL source (lower case), None for a device index or a file."""
    if "://" not in source:
        return None
    try:
        host = urlsplit(source).hostname
    except ValueError:
        return None
    return host or None
