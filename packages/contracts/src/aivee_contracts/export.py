"""Write the JSON Schema of every contract to packages/contracts/schema/."""

import json
from pathlib import Path

from pydantic import BaseModel

from aivee_contracts.events import (
    AlertEvent,
    DeviceStatus,
    Metrics,
    StaffProfiles,
    StaffSuggestion,
)
from aivee_contracts.geometry import CameraConfig, DeviceConfig, Zone
from aivee_contracts.rules import Rule, RuleSet

MODELS: list[type[BaseModel]] = [
    Zone,
    CameraConfig,
    DeviceConfig,
    Rule,
    RuleSet,
    AlertEvent,
    DeviceStatus,
    Metrics,
    StaffSuggestion,
    StaffProfiles,
]

OUT = Path(__file__).resolve().parents[2] / "schema"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for model in MODELS:
        schema = model.model_json_schema()
        path = OUT / f"{model.__name__}.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(MODELS)} schemas to {OUT}")


if __name__ == "__main__":
    main()
