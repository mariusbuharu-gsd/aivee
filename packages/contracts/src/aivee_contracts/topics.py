from dataclasses import dataclass

ROOT = "aivee"


@dataclass(frozen=True)
class Topics:
    """MQTT topic names for one edge device. See docs/contracts.md for QoS/retain."""

    site: str
    device: str

    def _t(self, leaf: str) -> str:
        return f"{ROOT}/{self.site}/{self.device}/{leaf}"

    @property
    def status(self) -> str:  # edge → retained, QoS 1, LWT "offline"
        return self._t("status")

    @property
    def events(self) -> str:  # edge → QoS 1
        return self._t("events")

    @property
    def metrics(self) -> str:  # edge → QoS 0
        return self._t("metrics")

    @property
    def suggestions(self) -> str:  # edge → QoS 1
        return self._t("suggestions")

    @property
    def rules(self) -> str:  # api → edge, retained, QoS 1
        return self._t("rules")

    @property
    def profiles(self) -> str:  # api → edge, retained, QoS 1
        return self._t("profiles")

    def snapshot(self, event_id: str) -> str:  # edge → QoS 1, JPEG bytes
        return self._t(f"snapshots/{event_id}")

    @staticmethod
    def shared_events() -> str:
        """Shared subscription: ingest workers split the event stream between them."""
        return f"$share/ingest/{ROOT}/+/+/events"

    @staticmethod
    def all_from_devices() -> str:
        return f"{ROOT}/+/+/#"
