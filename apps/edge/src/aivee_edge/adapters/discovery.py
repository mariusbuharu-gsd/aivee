"""Camera discovery's sockets: which LAN the device is on, the ONVIF WS-Discovery multicast
probe, a bounded TCP check of the RTSP ports, and the kernel's ARP table. The parsing and
merging is in `domain.discovery`.

`CameraDiscovery.discover()` runs the probe (about 3 s) next to the port check (at most about
5 s, 128 connects at a time, only the device's own /24 networks), so it answers in about 5 s.
Docker, bridge, VPN and loopback interfaces are skipped: the venue's cameras are on its LAN.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from aivee_contracts.commands import DiscoveredCamera

from aivee_edge.domain.discovery import (
    SCAN_PORTS,
    WS_DISCOVERY_ADDR,
    WS_DISCOVERY_PORT,
    OnvifDevice,
    merge_found,
    parse_probe_matches,
    probe_message,
    scan_hosts,
)

log = logging.getLogger("aivee_edge.discovery")

PROBE_S = 3.0
CONNECT_S = 0.8
SCAN_BUDGET_S = 5.0
SCAN_CONCURRENCY = 128

_SKIP_INTERFACE = re.compile(
    r"^(lo|docker|br-|veth|virbr|cni|flannel|cali|vxlan|weave|tun|tap|wg|zt|tailscale|vmnet|"
    r"vboxnet|utun|llw|awdl)",
    re.IGNORECASE,
)


def _psutil_addrs() -> Mapping[str, Sequence[Any]]:
    import psutil  # type: ignore[import-untyped, import-not-found, unused-ignore]

    return psutil.net_if_addrs()  # type: ignore[no-any-return]


def _psutil_stats() -> Mapping[str, Any]:
    import psutil  # type: ignore[import-untyped, import-not-found, unused-ignore]

    return psutil.net_if_stats()  # type: ignore[no-any-return]


def lan_addresses(
    addrs: Callable[[], Mapping[str, Sequence[Any]]] = _psutil_addrs,
    stats: Callable[[], Mapping[str, Any]] = _psutil_stats,
) -> list[str]:
    """The device's IPv4 addresses on interfaces that are up, without loopback, link-local,
    Docker, bridge and VPN interfaces."""
    up = stats()
    out: list[str] = []
    for name, entries in addrs().items():
        if _SKIP_INTERFACE.match(name) or not getattr(up.get(name), "isup", False):
            continue
        for entry in entries:
            if entry.family != socket.AF_INET:
                continue
            ip = str(entry.address)
            if ip.startswith(("127.", "169.254.")) or ip in out:
                continue
            out.append(ip)
    return out


def ws_discover(
    own_ips: Sequence[str],
    timeout_s: float = PROBE_S,
    *,
    socket_factory: Callable[..., Any] = socket.socket,
    clock: Callable[[], float] = time.monotonic,
) -> list[OnvifDevice]:
    """Send one ONVIF Probe out of every interface and collect the answers for `timeout_s`."""
    sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    found: dict[str, OnvifDevice] = {}
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.bind(("", 0))
        probe = probe_message(f"uuid:{uuid.uuid4()}")
        sent = 0
        for ip in own_ips:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                sock.sendto(probe, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
                sent += 1
            except OSError as e:
                log.warning("discovery_probe_failed interface=%s: %s", ip, e)
        deadline = clock() + timeout_s
        while sent and (left := deadline - clock()) > 0:
            sock.settimeout(left)
            try:
                payload, (sender, _port) = sock.recvfrom(65535)
            except (TimeoutError, OSError):
                break
            for dev in parse_probe_matches(payload, sender):
                found.setdefault(dev.ip, dev)
    finally:
        sock.close()
    return list(found.values())


Connect = Callable[[str, int, float], Awaitable[bool]]


async def _tcp_open(ip: str, port: int, timeout_s: float) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout_s)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError, TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), timeout_s)
    return True


def scan_ports(
    hosts: Sequence[str],
    ports: Sequence[int] = SCAN_PORTS,
    *,
    timeout_s: float = CONNECT_S,
    budget_s: float = SCAN_BUDGET_S,
    concurrency: int = SCAN_CONCURRENCY,
    connect: Connect = _tcp_open,
) -> dict[str, set[int]]:
    """ip → open ports among `ports`, at most `concurrency` connects at a time; whatever is
    not checked within `budget_s` counts as closed."""

    async def main() -> dict[str, set[int]]:
        gate = asyncio.Semaphore(concurrency)
        found: dict[str, set[int]] = {}

        async def one(ip: str, port: int) -> None:
            async with gate:
                if await connect(ip, port, timeout_s):
                    found.setdefault(ip, set()).add(port)

        tasks = [asyncio.create_task(one(ip, port)) for ip in hosts for port in ports]
        if not tasks:
            return found
        _done, pending = await asyncio.wait(tasks, timeout=budget_s)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return found

    return asyncio.run(main())


def arp_table(path: Path = Path("/proc/net/arp")) -> dict[str, str]:
    """ip → MAC of the neighbours the kernel knows (Linux); empty elsewhere."""
    try:
        lines = path.read_text().splitlines()[1:]
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in lines:
        cols = line.split()
        if len(cols) >= 4 and cols[3] != "00:00:00:00:00:00":
            out[cols[0]] = cols[3].lower()
    return out


class CameraDiscovery:
    def __init__(
        self,
        *,
        addresses: Callable[[], list[str]] = lan_addresses,
        probe: Callable[[list[str]], list[OnvifDevice]] = ws_discover,
        scan: Callable[[list[str], tuple[int, ...]], dict[str, set[int]]] = scan_ports,
        arp: Callable[[], Mapping[str, str]] = arp_table,
    ) -> None:
        self._addresses = addresses
        self._probe = probe
        self._scan = scan
        self._arp = arp

    def discover(self) -> list[DiscoveredCamera]:
        started = time.monotonic()
        own = self._addresses()
        if not own:
            log.warning("discovery found=0: no LAN interface (only loopback, Docker or VPN)")
            return []
        with ThreadPoolExecutor(1, thread_name_prefix="onvif probe") as pool:
            onvif = pool.submit(self._probe, own)
            ports = self._scan(scan_hosts(own), SCAN_PORTS)
            devices = onvif.result()
        found = merge_found(devices, ports, self._arp())  # ARP is fresh after the port check
        log.info(
            "discovery found=%d onvif=%d networks=%s seconds=%.1f",
            len(found),
            len(devices),
            ",".join(own),
            time.monotonic() - started,
        )
        return found
