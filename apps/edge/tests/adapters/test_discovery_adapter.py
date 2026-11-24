"""Camera discovery's sockets, faked: interfaces, the ONVIF multicast probe, the port check
and the ARP table. Nothing here touches the network."""

import asyncio
import socket
import time
from collections import namedtuple
from pathlib import Path
from typing import Any

from aivee_edge.adapters.discovery import (
    CameraDiscovery,
    arp_table,
    lan_addresses,
    scan_ports,
    ws_discover,
)
from aivee_edge.domain.discovery import WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT, OnvifDevice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "onvif"
Addr = namedtuple("Addr", "family address netmask broadcast ptp")
Stats = namedtuple("Stats", "isup")


def test_lan_addresses_skip_loopback_docker_bridges_and_down_links() -> None:
    addrs = {
        "lo": [Addr(socket.AF_INET, "127.0.0.1", "255.0.0.0", None, None)],
        "wlp0s20f3": [
            Addr(socket.AF_INET, "192.168.1.10", "255.255.255.0", None, None),
            Addr(socket.AF_INET6, "fe80::1", None, None, None),
        ],
        "enp3s0": [Addr(socket.AF_INET, "10.0.0.5", "255.255.255.0", None, None)],
        "docker0": [Addr(socket.AF_INET, "172.17.0.1", "255.255.0.0", None, None)],
        "br-1a2b3c": [Addr(socket.AF_INET, "172.18.0.1", "255.255.0.0", None, None)],
        "veth12ab": [Addr(socket.AF_INET, "169.254.3.3", "255.255.0.0", None, None)],
        "tailscale0": [Addr(socket.AF_INET, "100.64.0.7", "255.192.0.0", None, None)],
        "eth1": [Addr(socket.AF_INET, "192.168.50.2", "255.255.255.0", None, None)],
    }
    stats = {name: Stats(name != "eth1") for name in addrs}
    assert lan_addresses(lambda: addrs, lambda: stats) == ["192.168.1.10", "10.0.0.5"]


class FakeUdp:
    """A UDP socket that answers a Probe with the given (payload, sender) datagrams."""

    def __init__(self, answers: list[tuple[bytes, str]]) -> None:
        self.answers = list(answers)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.options: list[tuple[int, int, Any]] = []
        self.closed = False

    def setsockopt(self, level: int, option: int, value: Any) -> None:
        self.options.append((level, option, value))

    def bind(self, addr: tuple[str, int]) -> None: ...

    def settimeout(self, _t: float) -> None: ...

    def sendto(self, data: bytes, addr: tuple[str, int]) -> int:
        self.sent.append((data, addr))
        return len(data)

    def recvfrom(self, _n: int) -> tuple[bytes, tuple[str, int]]:
        if not self.answers:
            raise TimeoutError
        payload, sender = self.answers.pop(0)
        return payload, (sender, 3702)

    def close(self) -> None:
        self.closed = True


def test_ws_discover_probes_every_interface_and_reads_the_answers() -> None:
    tapo = (FIXTURES / "tapo.xml").read_bytes()
    fake = FakeUdp([(tapo, "192.168.1.21"), (b"junk", "192.168.1.99"), (tapo, "192.168.1.21")])
    found = ws_discover(
        ["192.168.1.10", "10.0.0.5"], timeout_s=0.5, socket_factory=lambda *_a: fake
    )
    assert found == [OnvifDevice(ip="192.168.1.21", name="TP-IPC", hardware="C210", mac=None)]
    assert [addr for _data, addr in fake.sent] == [(WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT)] * 2
    multicast_ifs = [v for _l, o, v in fake.options if o == socket.IP_MULTICAST_IF]
    assert multicast_ifs == [socket.inet_aton("192.168.1.10"), socket.inet_aton("10.0.0.5")]
    assert fake.closed


def test_ws_discover_survives_an_interface_it_cannot_send_on() -> None:
    class NoRoute(FakeUdp):
        def sendto(self, data: bytes, addr: tuple[str, int]) -> int:
            raise OSError("Network is unreachable")

    assert (
        ws_discover(["192.168.1.10"], timeout_s=0.1, socket_factory=lambda *_a: NoRoute([])) == []
    )


def test_scan_ports_reports_open_ports_within_its_budget() -> None:
    open_ = {("192.168.1.21", 554), ("192.168.1.21", 2020), ("192.168.1.40", 554)}

    async def connect(ip: str, port: int, _timeout: float) -> bool:
        if ip == "192.168.1.66":
            await asyncio.sleep(10)  # a host that never answers
        return (ip, port) in open_

    hosts = ["192.168.1.21", "192.168.1.40", "192.168.1.66", "192.168.1.70"]
    started = time.monotonic()
    found = scan_ports(hosts, (554, 2020), budget_s=0.3, concurrency=4, connect=connect)
    assert time.monotonic() - started < 2
    assert found == {"192.168.1.21": {554, 2020}, "192.168.1.40": {554}}


def test_scan_ports_limits_concurrency() -> None:
    running, peak = 0, 0

    async def connect(_ip: str, _port: int, _timeout: float) -> bool:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.001)
        running -= 1
        return False

    hosts = [f"10.0.0.{i}" for i in range(1, 60)]
    assert scan_ports(hosts, (554, 2020), concurrency=8, connect=connect) == {}
    assert peak <= 8


def test_arp_table(tmp_path: Path) -> None:
    arp = tmp_path / "arp"
    arp.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.21     0x1         0x2         98:da:c4:01:02:03     *        wlp0s20f3\n"
        "192.168.1.30     0x1         0x0         00:00:00:00:00:00     *        wlp0s20f3\n"
    )
    assert arp_table(arp) == {"192.168.1.21": "98:da:c4:01:02:03"}
    assert arp_table(tmp_path / "missing") == {}


def test_discovery_merges_onvif_ports_and_macs() -> None:
    probed: list[list[str]] = []

    def probe(own: list[str]) -> list[OnvifDevice]:
        probed.append(own)
        return [OnvifDevice(ip="192.168.1.64", name="HIKVISION X", hardware="DS-2CD", mac=None)]

    scanned: list[list[str]] = []

    def scan(hosts: list[str], _ports: tuple[int, ...]) -> dict[str, set[int]]:
        scanned.append(hosts)
        return {"192.168.1.21": {554, 2020}, "192.168.1.64": {554}}

    discovery = CameraDiscovery(
        addresses=lambda: ["192.168.1.10"],
        probe=probe,
        scan=scan,
        arp=lambda: {"192.168.1.21": "98:da:c4:01:02:03"},
    )
    found = discovery.discover()
    assert [(c.ip, c.brand, c.onvif) for c in found] == [
        ("192.168.1.21", "tapo", False),
        ("192.168.1.64", "hikvision", True),
    ]
    assert probed == [["192.168.1.10"]] and len(scanned[0]) == 253


def test_discovery_without_a_lan_finds_nothing() -> None:
    discovery = CameraDiscovery(
        addresses=lambda: [],
        probe=lambda _own: [OnvifDevice("1.2.3.4", None, None, None)],
        scan=lambda _h, _p: {"1.2.3.4": {554}},
        arp=dict,
    )
    assert discovery.discover() == []
