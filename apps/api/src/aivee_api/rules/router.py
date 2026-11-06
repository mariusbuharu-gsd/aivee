from typing import Annotated

from aivee_contracts.rules import Rule
from fastapi import APIRouter, Depends, status

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import RULES_MANAGE
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_camera, authorize_rule, camera_ids_at, rule_location
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Conflict
from aivee_api.rules.schemas import FromTextIn, FromTextOut, RuleIn, RulePatch
from aivee_api.rules.service import RuleService

router = APIRouter(prefix="/api/rules", tags=["rules"])

RulesAccess = Annotated[Access, Depends(require(RULES_MANAGE))]


def _target(rule: Rule) -> Target:
    return Target("rule", rule.id, rule.name)


async def _created(s: SessionDep, p: Principal, loc: str, rule: Rule) -> None:
    await record(
        s,
        p,
        "rule.created",
        location_id=loc,
        target=_target(rule),
        after=rule.model_dump(mode="json"),
    )


async def _check_new_id(s: SessionDep, p: Principal, rule_id: str | None) -> None:
    """An explicit id must not overwrite a rule of a location the caller cannot manage."""
    if rule_id is None:
        return
    existing = await rule_location(s, rule_id)
    if existing is not None and not p.can(RULES_MANAGE, existing):
        raise Conflict(f"Există deja o regulă cu id-ul {rule_id}.")


@router.get("")
async def list_rules(
    s: SessionDep, svc: ServicesDep, access: RulesAccess, camera_id: str | None = None
) -> list[Rule]:
    if camera_id is not None:
        await authorize_camera(s, access.principal, RULES_MANAGE, camera_id)
    ids = await camera_ids_at(s, access.location_id)
    rules = await RuleService(s, svc.sync).list_all(camera_id)
    return [r for r in rules if r.camera_id in ids]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(data: RuleIn, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> Rule:
    loc = await authorize_camera(s, p, RULES_MANAGE, data.camera_id)
    await _check_new_id(s, p, data.id)
    rule = await RuleService(s, svc.sync).create(data)
    await _created(s, p, loc, rule)
    return rule


@router.post("/from-text")
async def rule_from_text(
    data: FromTextIn, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> FromTextOut:
    """Romanian request → draft rule. Saved (and published) only when `save` is true."""
    loc = await authorize_camera(s, p, RULES_MANAGE, data.camera_id)
    service = RuleService(s, svc.sync)
    rule, explanation = await service.from_text(data.camera_id, data.text, svc.translator)
    if data.save:
        rule = await service.create(RuleIn.model_validate(rule.model_dump()))
        await _created(s, p, loc, rule)
    return FromTextOut(rule=rule, explanation_ro=explanation, saved=data.save)


@router.get("/{rule_id}")
async def get_rule(rule_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> Rule:
    await authorize_rule(s, p, RULES_MANAGE, rule_id)
    return await RuleService(s, svc.sync).get(rule_id)


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: str, patch: RulePatch, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> Rule:
    loc = await authorize_rule(s, p, RULES_MANAGE, rule_id)
    service = RuleService(s, svc.sync)
    before = await service.get(rule_id)
    rule = await service.update(rule_id, patch)
    await record(
        s,
        p,
        "rule.updated",
        location_id=loc,
        target=_target(rule),
        before=before.model_dump(mode="json"),
        after=rule.model_dump(mode="json"),
    )
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> None:
    loc = await authorize_rule(s, p, RULES_MANAGE, rule_id)
    service = RuleService(s, svc.sync)
    before = await service.get(rule_id)
    await service.delete(rule_id)
    await record(
        s,
        p,
        "rule.deleted",
        location_id=loc,
        target=_target(before),
        before=before.model_dump(mode="json"),
    )
