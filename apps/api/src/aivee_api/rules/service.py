import re
import uuid

from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, Action, Condition, Rule
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.db.repositories import CameraRepository, RuleRepository, camera_config
from aivee_api.edge.sync import EdgeSync
from aivee_api.errors import NotFound
from aivee_api.rules.prompt import COCO_CLASSES
from aivee_api.rules.schemas import RuleIn, RulePatch
from aivee_api.rules.translator import RuleDraft, RuleTranslator, TranslationError


def new_rule_id() -> str:
    return f"r-{uuid.uuid4().hex[:10]}"


class RuleService:
    def __init__(self, session: AsyncSession, sync: EdgeSync) -> None:
        self._s = session
        self._rules = RuleRepository(session)
        self._cameras = CameraRepository(session)
        self._sync = sync

    async def list_all(self, camera_id: str | None = None) -> list[Rule]:
        return await self._rules.list_all(camera_id)

    async def get(self, rule_id: str) -> Rule:
        rule = await self._rules.get(rule_id)
        if rule is None:
            raise NotFound(f"Regula {rule_id} nu există.")
        return rule

    async def create(self, data: RuleIn) -> Rule:
        await self._zones(data.camera_id)
        rule = Rule.model_validate({**data.model_dump(), "id": data.id or new_rule_id()})
        return await self._save(rule)

    async def update(self, rule_id: str, patch: RulePatch) -> Rule:
        current = await self.get(rule_id)
        changes = patch.model_dump(exclude_unset=True)
        rule = Rule.model_validate({**current.model_dump(), **changes})
        return await self._save(rule)

    async def delete(self, rule_id: str) -> None:
        if not await self._rules.delete(rule_id):
            raise NotFound(f"Regula {rule_id} nu există.")
        await self._s.commit()
        await self._sync.publish_rules()

    async def from_text(
        self, camera_id: str, text: str, translator: RuleTranslator
    ) -> tuple[Rule, str]:
        zones = await self._zones(camera_id)
        draft = await translator.translate(text, zones)
        return draft_to_rule(draft, camera_id, text, zones), draft.explanation_ro

    async def _save(self, rule: Rule) -> Rule:
        await self._rules.upsert(rule)
        await self._s.commit()
        await self._sync.publish_rules()
        return rule

    async def _zones(self, camera_id: str) -> list[Zone]:
        row = await self._cameras.get(camera_id)
        if row is None:
            raise NotFound(f"Camera {camera_id} nu există.")
        return camera_config(row).zones


# People are in almost every restaurant frame and they hold or stand next to what a visual
# rule looks for (a lit lighter, a knife, a phone). A person prompt in `negative` then wins
# the comparison: live, a lighter flame scored 0.00 with it and 1.00 without, while 13 normal
# frames stayed at or below 0.24 (threshold 0.5).
_PERSON = re.compile(
    r"\b(person|persons|people|man|men|woman|women|someone|somebody|crowd|guests?|"
    r"customers?|diners?|waiters?|staff|hands?)\b",
    re.IGNORECASE,
)
_FIRE = re.compile(r"\b(fire|flames?|burning)\b", re.IGNORECASE)
# A flame at the demo is a lighter in someone's hand, not a burning room.
SMALL_FLAME = ("a lighter with a flame", "a small open flame", "a hand holding a lit lighter")


def clean_visual(c: Condition) -> Condition:
    """Drop person prompts from a visual condition's negatives; add small-flame positives
    to a fire rule. Other kinds pass unchanged."""
    if c.kind != "visual":
        return c
    negative = [p for p in c.negative if not _PERSON.search(p)]
    positive = list(c.positive)
    if any(_FIRE.search(p) for p in positive):
        positive += [p for p in SMALL_FLAME if p not in positive]
    return c.model_copy(update={"positive": positive, "negative": negative})


def draft_to_rule(draft: RuleDraft, camera_id: str, text: str, zones: list[Zone]) -> Rule:
    """Check the model's draft against the camera and turn it into a full Rule."""
    if not draft.understood:
        raise TranslationError(
            "clarify", draft.clarification_ro or "Nu am înțeles cererea. Puteți reformula?"
        )
    open_kinds = {"object_present", "visual"}
    anywhere_ok = bool(draft.all_of) and all(c.kind in open_kinds for c in draft.all_of)
    tags = {z.tag for z in zones} | ({ANYWHERE_TAG} if anywhere_ok else set())
    if draft.zone_tag not in tags:
        raise TranslationError(
            "clarify",
            f"Camera nu are nicio zonă de tip „{draft.zone_tag}”. Desenați-o mai întâi.",
        )
    unknown = sorted(
        {o for c in draft.all_of if c.kind == "object_present" for o in c.objects}
        - set(COCO_CLASSES)
    )
    if unknown:
        raise TranslationError(
            "clarify",
            "AiVee nu recunoaște încă acest obiect pe cameră. Încercați să descrieți ce se vede "
            "(de exemplu „dacă e foc”) sau alegeți un obiect obișnuit.",
        )
    try:
        return Rule(
            id=new_rule_id(),
            camera_id=camera_id,
            name=draft.name,
            prompt_ro=text,
            zone_tag=draft.zone_tag,
            all_of=[clean_visual(c) for c in draft.all_of],
            action=Action(type="telegram"),
            cooldown_s=max(0, draft.cooldown_s),
        )
    except ValidationError as e:
        raise TranslationError(
            "invalid", "Nu am reușit să construiesc o regulă validă. Reformulați cererea."
        ) from e
