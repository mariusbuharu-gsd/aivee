"""Camera discovery, the pure part: WS-Discovery probe and answers, brand and RTSP path guess,
and merging ONVIF answers with open RTSP ports."""

from pathlib import Path

import pytest
from aivee_edge.domain.discovery import (
    OnvifDevice,
    brand_from_mac,
    brand_from_text,
    merge_found,
    parse_probe_matches,
    probe_message,
    rtsp_paths,
    scan_hosts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "onvif"


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.xml").read_bytes()


def test_probe_asks_for_video_transmitters_with_our_message_id() -> None:
    xml = probe_message("uuid:6f1f2b0e-9a49-4a4e-8b8a-0d6f9c2f3a11").decode()
    assert "<wsa:MessageID>uuid:6f1f2b0e-9a49-4a4e-8b8a-0d6f9c2f3a11</wsa:MessageID>" in xml
    assert "dn:NetworkVideoTransmitter" in xml
    assert "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe<" in xml


def test_a_tapo_answer() -> None:
    [dev] = parse_probe_matches(_fixture("tapo"), sender="192.168.1.21")
    assert dev == OnvifDevice(ip="192.168.1.21", name="TP-IPC", hardware="C210", mac=None)
    assert brand_from_text(dev.name, dev.hardware) == "tapo"


def test_a_hikvision_answer_prefers_the_ipv4_xaddr_and_reads_the_mac() -> None:
    [dev] = parse_probe_matches(_fixture("hikvision"), sender="192.168.1.250")
    assert dev.ip == "192.168.1.64"  # from XAddrs, not the UDP sender
    assert dev.name == "HIKVISION DS-2CD2143G2-I"
    assert dev.hardware == "DS-2CD2143G2-I"
    assert dev.mac == "c0:56:e3:11:22:33"
    assert brand_from_text(dev.name, dev.hardware) == "hikvision"


@pytest.mark.parametrize(
    ("fixture", "ip", "brand", "model"),
    [
        ("dahua", "192.168.1.108", "dahua", "IPC-HDW1230S"),
        ("reolink", "192.168.1.30", "reolink", "RLC-510A"),
    ],
)
def test_other_brands(fixture: str, ip: str, brand: str, model: str) -> None:
    [dev] = parse_probe_matches(_fixture(fixture), sender=ip)
    assert dev.ip == ip and dev.hardware == model
    assert brand_from_text(dev.name, dev.hardware) == brand


@pytest.mark.parametrize(
    "payload",
    [
        b"not xml at all",
        b"<a><b></a>",
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        b"<Envelope><Body><Hello/></Body></Envelope>",
    ],
)
def test_junk_and_entity_tricks_give_nothing(payload: bytes) -> None:
    assert parse_probe_matches(payload, sender="192.168.1.9") == []


def test_a_match_without_xaddrs_uses_the_sender() -> None:
    xml = (
        b'<e:Envelope xmlns:e="x" xmlns:d="y"><e:Body><d:ProbeMatches><d:ProbeMatch>'
        b"<d:Scopes>onvif://www.onvif.org/name/Cam</d:Scopes>"
        b"</d:ProbeMatch></d:ProbeMatches></e:Body></e:Envelope>"
    )
    assert parse_probe_matches(xml, sender="192.168.1.77") == [
        OnvifDevice(ip="192.168.1.77", name="Cam", hardware=None, mac=None)
    ]


@pytest.mark.parametrize(
    ("texts", "brand"),
    [
        (("Tapo C200", None), "tapo"),
        (("TP-Link", "C100"), "tapo"),
        ((None, "DS-2CD1023G0E-I"), "hikvision"),
        (("DH-IPC-HFW1230S", None), "dahua"),
        ((None, "RLC-810A"), "reolink"),
        (("IPCAM", "H264"), "unknown"),
        ((None, None), "unknown"),
    ],
)
def test_brand_from_text(texts: tuple[str | None, str | None], brand: str) -> None:
    assert brand_from_text(*texts) == brand


def test_brand_from_mac_oui() -> None:
    assert brand_from_mac("C0:56:E3:11:22:33") == "hikvision"
    assert brand_from_mac("3c-ef-8c-00-00-01") == "dahua"
    assert brand_from_mac("ec:71:db:aa:bb:cc") == "reolink"
    assert brand_from_mac("00:11:22:33:44:55") == "unknown"
    assert brand_from_mac(None) == "unknown"


def test_rtsp_paths_substream_first() -> None:
    assert rtsp_paths("tapo") == ["/stream2", "/stream1"]
    assert rtsp_paths("hikvision") == ["/Streaming/Channels/102"]
    assert rtsp_paths("dahua") == ["/cam/realmonitor?channel=1&subtype=1"]
    assert rtsp_paths("reolink") == ["/h264Preview_01_sub"]
    assert rtsp_paths("unknown") == []


def test_scan_hosts_are_the_own_slash_24s_without_own_addresses() -> None:
    hosts = scan_hosts(["192.168.1.10", "192.168.1.11", "10.20.30.40"])
    assert len(hosts) == 252 + 253  # 254 hosts per /24, minus our own addresses
    assert "192.168.1.10" not in hosts and "192.168.1.11" not in hosts
    assert {"192.168.1.1", "192.168.1.254", "10.20.30.1"} <= set(hosts)
    assert "192.168.1.0" not in hosts and "192.168.1.255" not in hosts
    assert len(scan_hosts([f"10.0.{i}.1" for i in range(10)], max_networks=4)) == 4 * 253


def test_merge_combines_onvif_ports_and_macs() -> None:
    onvif = [
        OnvifDevice(ip="192.168.1.21", name="TP-IPC", hardware="C210", mac=None),
        OnvifDevice(ip="192.168.1.64", name="IPCAM", hardware="X1", mac="c0:56:e3:11:22:33"),
    ]
    ports = {
        "192.168.1.21": {554, 2020},
        "192.168.1.9": {554},  # no ONVIF answer, unknown MAC
        "192.168.1.5": {2020},  # ONVIF port only: Tapo with RTSP off? not a camera we can read
        "192.168.1.40": {554, 2020},  # ONVIF off, but Tapo's ONVIF port is open
        "192.168.1.50": {554},
    }
    macs = {"192.168.1.50": "ec:71:db:01:02:03", "192.168.1.9": "00:11:22:33:44:55"}
    found = merge_found(onvif, ports, macs)
    assert [(c.ip, c.brand, c.onvif) for c in found] == [
        ("192.168.1.9", "unknown", False),
        ("192.168.1.21", "tapo", True),
        ("192.168.1.40", "tapo", False),
        ("192.168.1.50", "reolink", False),
        ("192.168.1.64", "hikvision", True),
    ]
    tapo = found[1]
    assert (tapo.port, tapo.model, tapo.name, tapo.rtsp_paths) == (
        554,
        "C210",
        "TP-IPC",
        ["/stream2", "/stream1"],
    )
    assert found[0].rtsp_paths == []
