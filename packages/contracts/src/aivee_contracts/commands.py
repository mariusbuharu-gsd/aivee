from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CommandKind = Literal["confirm_staff", "reject_staff"]


class EdgeCommand(BaseModel):
    """Sent by the API on `commands` (QoS 1, not retained): the owner decided a suggestion."""

    command_id: str = Field(description="UUID; lets the edge drop a redelivered command")
    kind: CommandKind
    camera_id: str
    track_id: int
    suggestion_id: str
    at: datetime
