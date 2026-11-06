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

    @property
    def config(self) -> str:  # api → edge, retained, QoS 1 (DeviceConfig: cameras + zones)
        return self._t("config")

    def snapshot(self, event_id: str) -> str:  # edge → QoS 1, JPEG bytes
        return self._t(f"snapshots/{event_id}")

    @staticmethod
    def any_device(leaf: str) -> str:
        """Wildcard over every site and device, e.g. any_device("status")."""
        return f"{ROOT}/+/+/{leaf}"

    @staticmethod
    def shared(leaf: str, group: str = "ingest") -> str:
        """Shared subscription: workers in `group` split the stream between them."""
        return f"$share/{group}/{ROOT}/+/+/{leaf}"

    @staticmethod
    def shared_events() -> str:
        return Topics.shared("events")

    @staticmethod
    def shared_suggestions() -> str:
        return Topics.shared("suggestions")

    @staticmethod
    def all_from_devices() -> str:
        return f"{ROOT}/+/+/#"
