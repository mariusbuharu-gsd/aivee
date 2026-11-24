"""Finding IP cameras on the venue network: the pure part (no sockets).

Two sources, merged by IP (`merge_found`):

- ONVIF WS-Discovery: a SOAP `Probe` sent to 239.255.255.250:3702 (`probe_message`); cameras
  answer with `ProbeMatches` naming their service address (`XAddrs`) and `Scopes` such as
  `onvif://www.onvif.org/name/…` and `…/hardware/…` (`parse_probe_matches`).
- A bounded TCP check of the RTSP port 554 and Tapo's ONVIF port 2020 on the device's own
  /24 networks (`scan_hosts`), for cameras with ONVIF switched off.

The brand comes from the ONVIF name or hardware (`brand_from_text`), else the MAC address's
vendor prefix (`brand_from_mac`), else an open port 2020 (Tapo), else "unknown". Each brand
gets its usual RTSP paths, substream first (`rtsp_paths`).
"""

import ipaddress
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from aivee_contracts.commands import CameraBrand, DiscoveredCamera

WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702
RTSP_PORT = 554
TAPO_ONVIF_PORT = 2020
SCAN_PORTS = (RTSP_PORT, TAPO_ONVIF_PORT)

_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header>
<wsa:MessageID>{message_id}</wsa:MessageID>
<wsa:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
<wsa:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
</e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""


def probe_message(message_id: str) -> bytes:
    """A WS-Discovery Probe for ONVIF video transmitters; `message_id` like `uuid:…`."""
    return _PROBE.format(message_id=message_id).encode()


@dataclass(frozen=True)
class OnvifDevice:
    """One `ProbeMatch`: where the camera is and what its scopes say about it."""

    ip: str
    name: str | None
    hardware: str | None
    mac: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _ipv4(text: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        return None


def _xaddr_ipv4(xaddrs: str) -> str | None:
    for url in xaddrs.split():
        try:
            host = urlsplit(url).hostname
        except ValueError:
            continue
        if host and (ip := _ipv4(host)):
            return ip
    return None


def _scopes(text: str) -> dict[str, str]:
    """`onvif://www.onvif.org/name/TP-IPC …` → {"name": "TP-IPC", …} (first of each key)."""
    out: dict[str, str] = {}
    for scope in text.split():
        head, _, tail = scope.partition("onvif://www.onvif.org/")
        if head or not tail:
            continue
        key, _, value = tail.partition("/")
        if value:
            out.setdefault(key.lower(), unquote(value).strip())
    return out


def parse_probe_matches(payload: bytes, sender: str) -> list[OnvifDevice]:
    """Every `ProbeMatch` in one WS-Discovery answer. `sender` (the UDP source address)
    stands in when no IPv4 `XAddrs` is given. Junk, and XML with a DOCTYPE or entities
    (nothing a camera needs), gives an empty list."""
    if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
        return []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    found: list[OnvifDevice] = []
    for match in root.iter():
        if _local(match.tag) != "ProbeMatch":
            continue
        ip = _xaddr_ipv4(_child_text(match, "XAddrs")) or _ipv4(sender)
        if ip is None:
            continue
        scopes = _scopes(_child_text(match, "Scopes"))
        found.append(
            OnvifDevice(
                ip=ip,
                name=scopes.get("name") or None,
                hardware=scopes.get("hardware") or None,
                mac=scopes.get("mac") or None,
            )
        )
    return found


_BRAND_WORDS: list[tuple[CameraBrand, re.Pattern[str]]] = [
    ("tapo", re.compile(r"tapo|tp-?link|tp-ipc", re.IGNORECASE)),
    ("hikvision", re.compile(r"hikvision|^ds-\d", re.IGNORECASE)),
    ("dahua", re.compile(r"dahua|^dh-|^ipc-h[dfw]", re.IGNORECASE)),
    ("reolink", re.compile(r"reolink|^rlc-|^rlk", re.IGNORECASE)),
]


def brand_from_text(*texts: str | None) -> CameraBrand:
    """The brand an ONVIF name or hardware model gives away, else "unknown"."""
    for text in texts:
        if not text:
            continue
        for brand, pattern in _BRAND_WORDS:
            if pattern.search(text.strip()):
                return brand
    return "unknown"


# Vendor prefixes (OUI) of the camera makers we have RTSP paths for. A short, well-known list:
# a wrong guess only means the owner picks the brand by hand.
_OUI: dict[str, CameraBrand] = {
    # Hikvision
    "28:57:be": "hikvision",
    "44:19:b6": "hikvision",
    "4c:bd:8f": "hikvision",
    "bc:ad:28": "hikvision",
    "c0:56:e3": "hikvision",
    # Dahua
    "3c:ef:8c": "dahua",
    "90:02:a9": "dahua",
    "e0:50:8b": "dahua",
    # Reolink
    "ec:71:db": "reolink",
    # TP-Link (Tapo)
    "50:c7:bf": "tapo",
    "60:32:b1": "tapo",
    "98:da:c4": "tapo",
}


def brand_from_mac(mac: str | None) -> CameraBrand:
    if not mac:
        return "unknown"
    prefix = mac.strip().lower().replace("-", ":")[:8]
    return _OUI.get(prefix, "unknown")


_PATHS: dict[CameraBrand, list[str]] = {
    "tapo": ["/stream2", "/stream1"],
    "hikvision": ["/Streaming/Channels/102"],
    "dahua": ["/cam/realmonitor?channel=1&subtype=1"],
    "reolink": ["/h264Preview_01_sub"],
    "unknown": [],
}


def rtsp_paths(brand: CameraBrand) -> list[str]:
    """Where the brand serves its RTSP streams, the substream (what detection reads) first."""
    return list(_PATHS[brand])


def scan_hosts(own_ips: Iterable[str], max_networks: int = 4) -> list[str]:
    """The hosts of each own address's /24 (at most `max_networks` of them), without the
    device's own addresses: the fallback check never leaves the venue's own subnets."""
    own = {ip for ip in own_ips if _ipv4(ip)}
    networks: list[ipaddress.IPv4Network] = []
    for ip in sorted(own, key=ipaddress.IPv4Address):
        net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        if net not in networks:
            networks.append(net)
    hosts: list[str] = []
    for net in networks[:max_networks]:
        hosts.extend(str(h) for h in net.hosts() if str(h) not in own)
    return hosts


def merge_found(
    onvif: Sequence[OnvifDevice],
    open_ports: Mapping[str, set[int]],
    macs: Mapping[str, str] | None = None,
) -> list[DiscoveredCamera]:
    """One `DiscoveredCamera` per IP that answered ONVIF or has RTSP (554) open, by IP."""
    macs = macs or {}
    by_ip = {d.ip: d for d in onvif}
    ips = set(by_ip) | {ip for ip, ports in open_ports.items() if RTSP_PORT in ports}
    found: list[DiscoveredCamera] = []
    for ip in sorted(ips, key=ipaddress.IPv4Address):
        dev = by_ip.get(ip)
        brand: CameraBrand = "unknown"
        if dev is not None:
            brand = brand_from_text(dev.name, dev.hardware)
        if brand == "unknown":
            brand = brand_from_mac(macs.get(ip) or (dev.mac if dev else None))
        if brand == "unknown" and TAPO_ONVIF_PORT in open_ports.get(ip, set()):
            brand = "tapo"
        found.append(
            DiscoveredCamera(
                ip=ip,
                port=RTSP_PORT,
                brand=brand,
                model=dev.hardware if dev else None,
                name=dev.name if dev else None,
                onvif=dev is not None,
                rtsp_paths=rtsp_paths(brand),
            )
        )
    return found
