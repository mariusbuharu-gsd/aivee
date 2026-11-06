"""The Telegram alert message: headline and explanation per rule kind, HTML, keyboard."""

from datetime import UTC, datetime

import pytest
from aivee_contracts.events import AlertEvent, ObjectChange, Verification
from aivee_contracts.rules import Condition
from aivee_ingest.alert_message import (
    AlertContext,
    ack_line,
    alert_ref,
    basic_context,
    headline_explanation,
    keyboard,
    public_https_url,
    render,
)

AT = datetime(2026, 11, 6, 14, 56, tzinfo=UTC)  # 16:56 in Bucharest


def _event(summary: str = "Masa 1: neservită de 1 min", **kw: object) -> AlertEvent:
    return AlertEvent(
        event_id="3f2c1e0a-0000-4000-8000-000000000001",
        rule_id="r1",
        camera_id="cam-01",
        zone_id="z-mw4t3c6b",
        state="opened",
        at=AT,
        summary_ro=summary,
        **kw,  # type: ignore[arg-type]
    )


def _ctx(
    conditions: list[Condition],
    summary: str = "Masa 1: neservită de 1 min",
    zone: str = "Masa 1",
    verification: Verification | None = None,
    **kw: object,
) -> AlertContext:
    return AlertContext(
        _event(summary, **kw),
        zone_name=zone,
        location_name="Terasa demo",
        camera_name="Sala principală",
        conditions=conditions,
        verification=verification,
    )


WAIT = [
    Condition(kind="present", role="guest", min_duration_s=10),
    Condition(kind="absent", role="staff", min_duration_s=60),
]


@pytest.mark.parametrize(
    ("ctx", "headline", "explanation"),
    [
        (_ctx(WAIT), "Masa 1 așteaptă de 1 min", "Nu a venit nimeni la client."),
        (
            _ctx(
                [Condition(kind="absent", role="staff", min_duration_s=130)],
                summary="Masa 1: neservită de 2 min",
            ),
            "Masa 1 așteaptă de 2 min 10 s",
            "Nu a venit nimeni la client.",
        ),
        (
            _ctx(
                [Condition(kind="pose", role="guest", pose="raised_hand")],
                summary="Masa 2: un client cheamă",
                zone="Masa 2",
            ),
            "Masa 2: un client cheamă",
            "Un client a ridicat mâna.",
        ),
        (
            _ctx(
                [Condition(kind="objects_unattended", objects=["cup"], min_duration_s=180)],
                summary="Masa 3: nedebarasată de 3 min",
                zone="Masa 3",
            ),
            "Masa 3 e nedebarasată de 3 min",
            "Clienții au plecat, masa n-a fost strânsă.",
        ),
        (
            _ctx(
                [Condition(kind="object_gone", objects=["wine glass"], min_duration_s=5)],
                summary="Masa 1: a dispărut paharul de vin",
                object_change=ObjectChange(objects=["wine glass"]),
            ),
            "Masa 1: a dispărut paharul de vin",
            "Verifică masa.",
        ),
        (
            _ctx(
                [Condition(kind="count", role="guest", min_count=3)],
                summary="Bar: 4 persoane așteaptă",
                zone="Bar",
            ),
            "Bar: 4 persoane așteaptă",
            "S-a strâns lume. Trimite pe cineva să ajute.",
        ),
        (
            _ctx(
                [Condition(kind="present", role="guest", min_duration_s=1800)],
                summary="Masa 5: ocupată de 30 min",
                zone="Masa 5",
            ),
            "Masa 5 e ocupată de 30 min",
            "Vezi dacă clienții au nevoie de ceva.",
        ),
        (_ctx([], summary="Masa 9: ceva nou"), "Masa 9: ceva nou", ""),
    ],
    ids=["wait", "wait-seconds", "hand", "uncleared", "gone", "count", "present", "unknown"],
)
def test_headline_and_explanation_per_kind(
    ctx: AlertContext, headline: str, explanation: str
) -> None:
    assert headline_explanation(ctx) == (headline, explanation)


def test_object_gone_names_the_verified_object_with_an_article() -> None:
    verified = Verification(
        status="confirmed", summary_ro="Masa 1: a dispărut paharul de vin", object_ro="pahar de vin"
    )
    ctx = _ctx(
        [Condition(kind="object_gone", objects=["wine glass"])],
        summary="Masa 1: a dispărut paharul de vin",
        verification=verified,
        object_change=ObjectChange(objects=["wine glass"]),
    )
    headline, explanation = headline_explanation(ctx)
    assert headline == "Masa 1: a dispărut un pahar de vin"
    assert explanation == "Masa 1: a dispărut paharul de vin"  # the model's summary
    bottle = Verification(status="confirmed", object_ro="sticlă")
    assert (
        headline_explanation(
            _ctx([Condition(kind="object_gone", objects=["bottle"])], verification=bottle)
        )[0]
        == "Masa 1: a dispărut o sticlă"
    )


def test_a_confirmed_check_replaces_the_explanation_other_statuses_do_not() -> None:
    confirmed = Verification(status="confirmed", summary_ro="Masa 1: doi clienți așteaptă")
    assert headline_explanation(_ctx(WAIT, verification=confirmed))[1] == (
        "Masa 1: doi clienți așteaptă"
    )
    for status in ("unavailable", "pending"):
        v = Verification(status=status, summary_ro="ignored")  # type: ignore[arg-type]
        assert headline_explanation(_ctx(WAIT, verification=v))[1] == (
            "Nu a venit nimeni la client."
        )


def test_rendered_message_matches_the_chosen_format() -> None:
    assert render(_ctx(WAIT)) == (
        "🔴 <b>Masa 1 așteaptă de 1 min</b>\n"
        "Nu a venit nimeni la client.\n"
        "\n"
        "📍 Terasa demo · Sala principală · 16:56"
    )


def test_html_is_escaped_and_plain_text_is_not() -> None:
    ctx = AlertContext(
        _event("x"),
        zone_name="Masa <1> & co",
        location_name="Bar <b>",
        camera_name="Cam & 2",
        conditions=WAIT,
    )
    text = render(ctx, prefix="[test]")
    assert text.startswith("[test] 🔴 <b>Masa &lt;1&gt; &amp; co așteaptă de 1 min</b>")
    assert "📍 Bar &lt;b&gt; · Cam &amp; 2 · 16:56" in text
    plain = render(ctx, prefix="[test]", as_html=False)
    assert plain.startswith("[test] 🔴 Masa <1> & co așteaptă de 1 min\n")
    assert "<b>" not in plain.splitlines()[0]


def test_ack_line_is_appended_in_local_time() -> None:
    text = render(_ctx(WAIT), extra=[ack_line("Ana <3", AT)])
    assert text.endswith("\n✋ Preluată de Ana &lt;3 · 16:56")


def test_basic_context_falls_back_to_ids() -> None:
    ctx = basic_context(_event())
    assert (ctx.zone_name, ctx.location_name, ctx.camera_name) == ("Masa 1", "", "cam-01")
    assert render(ctx).endswith("📍 cam-01 · 16:56")
    no_name = basic_context(_event("nimic"))
    assert no_name.zone_name == "z-mw4t3c6b"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://aivee.example.com", "https://aivee.example.com"),
        ("https://aivee.example.com/", "https://aivee.example.com"),
        ("http://aivee.example.com", None),
        ("https://localhost:5173", None),
        ("https://127.0.0.1", None),
        ("https://192.168.1.20:5173", None),
        ("https://laptop", None),
        ("https://box.local", None),
        ("https://8.8.8.8", "https://8.8.8.8"),
        ("", None),
        (None, None),
        ("not a url", None),
    ],
)
def test_public_https_url(url: str | None, ok: str | None) -> None:
    assert public_https_url(url) == ok


def test_keyboard_with_and_without_a_public_dashboard() -> None:
    alert = "3f2c1e0a-0000-4000-8000-000000000001"
    assert keyboard(alert, None) == {
        "inline_keyboard": [[{"text": "Preiau ✋", "callback_data": f"ack:{alert}"}]]
    }
    assert keyboard(alert, "http://localhost:5173") == keyboard(alert, None)
    assert keyboard(alert, "https://aivee.example.com/") == {
        "inline_keyboard": [
            [
                {"text": "Preiau ✋", "callback_data": f"ack:{alert}"},
                {"text": "Vezi în aplicație", "url": "https://aivee.example.com/alerte"},
            ]
        ]
    }
    assert keyboard(alert, None, with_ack=False) is None
    assert keyboard(alert, "https://aivee.example.com", with_ack=False) == {
        "inline_keyboard": [
            [{"text": "Vezi în aplicație", "url": "https://aivee.example.com/alerte"}]
        ]
    }
    # callback_data is limited to 64 bytes: no button rather than a refused message
    assert keyboard("x" * 70, None) is None


def test_alert_ref() -> None:
    assert alert_ref("ack:abc") == "abc"
    assert alert_ref("ack:") is None
    assert alert_ref("other:abc") is None
    assert alert_ref(None) is None
