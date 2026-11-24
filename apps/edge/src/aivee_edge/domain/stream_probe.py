"""Why a camera does not stream, the pure part (no sockets).

OpenCV says only "could not open", so the camera test asks the camera itself first: one RTSP
`DESCRIBE` (an HTTP `GET` for an MJPEG camera) without credentials, then, after a `401`, again
with Basic or Digest (RFC 2617) authentication built from the URL's user and password. The
status of the last answer (`verdict`) tells a wrong password from a wrong path.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}

Verdict = Literal["ok", "auth", "no_stream", "unknown"]


@dataclass(frozen=True)
class StreamTarget:
    """A camera URL split into what a probe needs; `uri` has no credentials."""

    scheme: str
    host: str
    port: int
    path: str
    """Path and query, as sent in an HTTP request line."""
    user: str | None
    password: str | None

    @property
    def uri(self) -> str:
        """The request URI of an RTSP DESCRIBE (and the Digest `uri` of RTSP)."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}{self.path}"

    @classmethod
    def parse(cls, source: str) -> "StreamTarget | None":
        try:
            parts = urlsplit(source.strip())
            port = parts.port
        except ValueError:
            return None
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS or not parts.hostname:
            return None
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        return cls(
            scheme=scheme,
            host=parts.hostname,
            port=port or DEFAULT_PORTS[scheme],
            path=path,
            user=unquote(parts.username) if parts.username is not None else None,
            password=unquote(parts.password) if parts.password is not None else None,
        )


def method(target: StreamTarget) -> str:
    return "DESCRIBE" if target.scheme.startswith("rtsp") else "GET"


def digest_uri(target: StreamTarget) -> str:
    return target.uri if target.scheme.startswith("rtsp") else target.path


def request(target: StreamTarget, cseq: int, auth: str | None = None) -> bytes:
    """One RTSP DESCRIBE or HTTP GET, with an `Authorization` header when given."""
    if target.scheme.startswith("rtsp"):
        lines = [
            f"DESCRIBE {target.uri} RTSP/1.0",
            f"CSeq: {cseq}",
            "Accept: application/sdp",
            "User-Agent: AiVee camera test",
        ]
    else:
        lines = [
            f"GET {target.path} HTTP/1.1",
            f"Host: {target.host}",
            "User-Agent: AiVee camera test",
            "Connection: close",
        ]
    if auth:
        lines.append(f"Authorization: {auth}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


@dataclass(frozen=True)
class Response:
    status: int
    challenges: list[str]
    """Every `WWW-Authenticate` value, in order."""


def parse_response(raw: bytes) -> Response | None:
    """The status line and the authentication challenges of an RTSP or HTTP answer; None
    when it is neither."""
    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    first = lines[0].split(" ", 2)
    if len(first) < 2 or not first[0].startswith(("RTSP/", "HTTP/")) or not first[1].isdigit():
        return None
    challenges = [
        value.strip()
        for name, sep, value in (line.partition(":") for line in lines[1:])
        if sep and name.strip().lower() == "www-authenticate"
    ]
    return Response(status=int(first[1]), challenges=challenges)


def _params(challenge: str) -> dict[str, str]:
    """`realm="x", nonce="y", qop="auth"` → dict (keys lower case, quotes removed)."""
    out: dict[str, str] = {}
    rest = challenge
    while rest:
        key, sep, rest = rest.partition("=")
        if not sep:
            break
        rest = rest.lstrip()
        if rest.startswith('"'):
            value, _, rest = rest[1:].partition('"')
        else:
            value, _, rest = rest.partition(",")
        out[key.strip(" ,").lower()] = value.strip()
        rest = rest.lstrip(" ,")
    return out


def _md5(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def authorization(
    challenges: list[str],
    user: str,
    password: str,
    method: str,
    uri: str,
    cnonce: str | None = None,
) -> str | None:
    """The `Authorization` value for the camera's challenges: Digest (MD5) when offered,
    else Basic; None when neither is offered."""
    digest = next((c for c in challenges if c.lower().startswith("digest ")), None)
    if digest is not None:
        p = _params(digest[len("digest ") :])
        realm, nonce = p.get("realm", ""), p.get("nonce", "")
        if p.get("algorithm", "MD5").upper() != "MD5" or not nonce:
            return None
        ha1 = _md5(f"{user}:{realm}:{password}")
        ha2 = _md5(f"{method}:{uri}")
        fields = [f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
        qops = [q.strip() for q in p.get("qop", "").split(",") if q.strip()]
        if "auth" in qops:
            cnonce = cnonce or secrets.token_hex(8)
            response = _md5(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
            fields += ["qop=auth", "nc=00000001", f'cnonce="{cnonce}"']
        else:
            response = _md5(f"{ha1}:{nonce}:{ha2}")
        fields.append(f'response="{response}"')
        if "opaque" in p:
            fields.append(f'opaque="{p["opaque"]}"')
        if "algorithm" in p:
            # Echo it only when asked: Tapo cameras refuse an `algorithm` they did not name.
            fields.append("algorithm=MD5")
        return "Digest " + ", ".join(fields)
    if any(c.lower().startswith("basic") for c in challenges):
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {token}"
    return None


def verdict(status: int) -> Verdict:
    """What the camera's last answer means for a camera test."""
    if 200 <= status < 300:
        return "ok"
    if status in (401, 403):
        return "auth"
    if status in (404, 454):
        return "no_stream"
    return "unknown"
