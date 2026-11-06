import asyncio
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.db.models import StaffProfileRow
from aivee_api.db.repositories import StaffRepository, SuggestionRepository
from aivee_api.edge.sync import EdgeCommands, EdgeSync, SuggestionDecision
from aivee_api.errors import Conflict, Invalid, NotFound, Unavailable
from aivee_api.events.schemas import SuggestionOut, suggestion_out
from aivee_api.staff.enrol import Enroller, Upload, l2_normalise
from aivee_api.staff.schemas import DecisionOut, EnrolOut, ProfileOut

NO_ENROLLER = "Înrolarea din poze nu este disponibilă pe acest server (lipsesc modelele)."


class StaffService:
    def __init__(
        self,
        session: AsyncSession,
        sync: EdgeSync,
        commands: EdgeCommands,
        enroller: Enroller | None,
        snapshot_dir: Path,
    ) -> None:
        self._s = session
        self._staff = StaffRepository(session)
        self._suggestions = SuggestionRepository(session)
        self._sync = sync
        self._commands = commands
        self._enroller = enroller
        self._snapshots = snapshot_dir

    async def pending_suggestions(self) -> list[SuggestionOut]:
        return [suggestion_out(r) for r in await self._suggestions.pending()]

    async def profiles(self) -> list[ProfileOut]:
        return [await self._profile_out(p) for p in await self._staff.profiles()]

    async def enrol(
        self, uploads: Sequence[Upload], profile_id: str, name: str, description_ro: str = ""
    ) -> EnrolOut:
        if not uploads:
            raise Invalid("Încărcați cel puțin o poză sau un video scurt.")
        if self._enroller is None:
            raise Unavailable(NO_ENROLLER)
        bad = [u.filename for u in uploads if not u.content_type.startswith(("image/", "video/"))]
        if bad:
            raise Invalid(f"Fișiere nesuportate (doar imagini sau video): {', '.join(bad)}")
        result = await asyncio.to_thread(self._enroller.enrol, list(uploads))
        profile = await self._ensure_profile(profile_id, name, description_ro)
        await self._add_examples(profile.id, result.embeddings, "upload")
        await self._s.commit()
        published = await self._sync.publish_profiles() if result.embeddings else False
        return EnrolOut(
            profile=await self._profile_out(profile),
            files=len(uploads),
            frames=result.frames,
            crops=result.crops,
            examples_added=len(result.embeddings),
            skipped=result.skipped,
            published=published,
        )

    async def decide(
        self, suggestion_id: str, confirmed: bool, profile_id: str, profile_name: str
    ) -> DecisionOut:
        row = await self._suggestions.get(suggestion_id)
        if row is None:
            raise NotFound(f"Sugestia {suggestion_id} nu există.")
        if row.status != "pending":
            raise Conflict(f"Sugestia a fost deja {_ro_status(row.status)}.")
        status = "confirmed" if confirmed else "rejected"
        await self._suggestions.set_status(suggestion_id, status)
        added = 0
        if confirmed:
            added = await self._learn_from_snapshot(suggestion_id, profile_id, profile_name)
        await self._s.commit()
        if added:
            await self._sync.publish_profiles()
        await self._commands.suggestion_decided(
            SuggestionDecision(
                suggestion_id, row.camera_id, row.track_id, confirmed, device_id=row.device_id
            )
        )
        return DecisionOut(suggestion_id=suggestion_id, status=status, examples_added=added)

    async def _learn_from_snapshot(self, suggestion_id: str, profile_id: str, name: str) -> int:
        """If the edge sent a snapshot for the suggestion, its crop becomes a staff example."""
        path = self._snapshots / f"{suggestion_id}.jpg"
        if self._enroller is None or not path.is_file():
            return 0
        upload = Upload(path.name, "image/jpeg", path.read_bytes())
        result = await asyncio.to_thread(self._enroller.enrol, [upload])
        profile = await self._ensure_profile(profile_id, name)
        await self._add_examples(profile.id, result.embeddings, "confirmed")
        return len(result.embeddings)

    async def _ensure_profile(
        self, profile_id: str, name: str, description_ro: str = ""
    ) -> StaffProfileRow:
        profile = await self._staff.get_profile(profile_id)
        if profile is None:
            profile = await self._staff.create_profile(profile_id, name, description_ro)
        elif description_ro:
            profile.description_ro = description_ro
        return profile

    async def _add_examples(
        self, profile_id: str, embeddings: Sequence[Sequence[float]], source: str
    ) -> None:
        if not embeddings:
            return
        for vec in embeddings:
            await self._staff.add_example(profile_id, vec, source)
        await self._staff.recompute_centroid(profile_id)
        profile = await self._staff.get_profile(profile_id)
        if profile is not None:
            await self._s.refresh(profile)
            if profile.centroid is not None:  # the contract wants an L2-normalised centroid
                await self._staff.set_centroid(profile_id, l2_normalise(profile.centroid))
                await self._s.refresh(profile)

    async def _profile_out(self, p: StaffProfileRow) -> ProfileOut:
        return ProfileOut(
            id=p.id,
            name=p.name,
            description_ro=p.description_ro,
            examples=await self._staff.example_count(p.id),
            has_centroid=p.centroid is not None,
        )


def _ro_status(status: str) -> str:
    return {"confirmed": "confirmată", "rejected": "respinsă"}.get(status, status)
