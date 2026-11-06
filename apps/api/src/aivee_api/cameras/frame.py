"""The latest still of a camera, for the dashboard (Dispozitive thumbnail, zone background).

No new frames are captured for this: it is the newest whole-frame alert snapshot ingest
already stored for the camera. The edge blurs faces before any snapshot leaves the device
(`aivee_edge.app.BlurredJpeg`), so this never serves an unblurred image. "Before" images
and staff-suggestion crops are not used: the first is older, the second shows one person.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.db.models import EventRow
from aivee_api.errors import NotFound
from aivee_api.events.service import snapshot_file

LOOKBACK = 5
"""Newest rows to try: ingest stores the row before its JPEG lands, so the newest may lack it."""


@dataclass(frozen=True)
class CameraFrame:
    path: Path
    at: datetime


async def latest_frame(s: AsyncSession, snapshot_dir: Path, camera_id: str) -> CameraFrame | None:
    rows = await s.execute(
        select(EventRow.event_id, EventRow.at)
        .where(EventRow.camera_id == camera_id, EventRow.snapshot_path.is_not(None))
        .order_by(EventRow.at.desc(), EventRow.id.desc())
        .limit(LOOKBACK)
    )
    for event_id, at in rows:
        try:
            return CameraFrame(snapshot_file(snapshot_dir, event_id), at)
        except NotFound:
            continue
    return None
