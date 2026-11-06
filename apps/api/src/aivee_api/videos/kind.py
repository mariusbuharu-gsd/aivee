"""Which devices and cameras belong to uploaded-clip analysis, by id.

The runner publishes as the MQTT user `MQTT_UPLOAD_USER` (default `upload-01`); the broker
ACL makes the topic's device id equal to that username, so an `upload-` device id cannot be
faked by a live edge. Its cameras are `video-<id>`. Ids decide, not a DB column, so ingest
never notifies staff about a clip even before (or without) the API's rows.
"""

from sqlalchemy import ColumnElement, and_
from sqlalchemy.orm import InstrumentedAttribute

UPLOAD_DEVICE_PREFIX = "upload-"
UPLOAD_CAMERA_PREFIX = "video-"
DEFAULT_UPLOAD_DEVICE = "upload-01"


def is_upload_device(device_id: str | None) -> bool:
    return bool(device_id) and str(device_id).startswith(UPLOAD_DEVICE_PREFIX)


def is_upload_camera(camera_id: str | None) -> bool:
    return bool(camera_id) and str(camera_id).startswith(UPLOAD_CAMERA_PREFIX)


def is_upload(device_id: str | None = None, camera_id: str | None = None) -> bool:
    """An event or alert from a clip: either id gives it away."""
    return is_upload_device(device_id) or is_upload_camera(camera_id)


def not_upload(
    device_id: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    camera_id: InstrumentedAttribute[str] | InstrumentedAttribute[str | None] | None = None,
) -> ColumnElement[bool]:
    """SQL: the row is from a live camera (NULL ids count as live)."""
    live = device_id.is_(None) | ~device_id.startswith(UPLOAD_DEVICE_PREFIX, autoescape=True)
    if camera_id is None:
        return live
    return and_(
        live, camera_id.is_(None) | ~camera_id.startswith(UPLOAD_CAMERA_PREFIX, autoescape=True)
    )
