"""Camera URLs without their secrets, for log lines and tool output (audit S11).

`rtsp://admin:s3cr3t@192.168.1.20:554/stream2` → `rtsp://admin:***@192.168.1.20:554/stream2`.
A user name alone (`rtsp://token@host`) may itself be a token, so it is hidden as `***`.
Query parameters that look like credentials (`password=`, `token=`, …) are masked too.
Anything that is not a URL (a webcam index, a file path) is returned unchanged.
"""

import re

MASK = "***"

_USERINFO = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/?#]*)@")
_SECRET_PARAM = re.compile(
    r"(?P<key>[?&;](?:pass(?:word)?|pwd|token|key|secret|auth|sig(?:nature)?)=)[^&#;]*",
    re.IGNORECASE,
)


def redact_url(url: str | int) -> str:
    """`url` with the password (or a bare user token) and secret query values masked."""
    text = str(url)
    m = _USERINFO.match(text)
    if m is not None:
        user, sep, _password = m.group("userinfo").partition(":")
        shown = f"{user}:{MASK}" if sep else MASK
        text = f"{m.group('scheme')}{shown}@{text[m.end() :]}"
    return _SECRET_PARAM.sub(lambda p: p.group("key") + MASK, text)
