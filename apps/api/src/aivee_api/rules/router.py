from aivee_contracts.rules import Rule
from fastapi import APIRouter, status

from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.rules.schemas import FromTextIn, FromTextOut, RuleIn, RulePatch
from aivee_api.rules.service import RuleService

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("")
async def list_rules(s: SessionDep, svc: ServicesDep, camera_id: str | None = None) -> list[Rule]:
    return await RuleService(s, svc.sync).list_all(camera_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(data: RuleIn, s: SessionDep, svc: ServicesDep) -> Rule:
    return await RuleService(s, svc.sync).create(data)


@router.post("/from-text")
async def rule_from_text(data: FromTextIn, s: SessionDep, svc: ServicesDep) -> FromTextOut:
    """Romanian request → draft rule. Saved (and published) only when `save` is true."""
    service = RuleService(s, svc.sync)
    rule, explanation = await service.from_text(data.camera_id, data.text, svc.translator)
    if data.save:
        rule = await service.create(RuleIn.model_validate(rule.model_dump()))
    return FromTextOut(rule=rule, explanation_ro=explanation, saved=data.save)


@router.get("/{rule_id}")
async def get_rule(rule_id: str, s: SessionDep, svc: ServicesDep) -> Rule:
    return await RuleService(s, svc.sync).get(rule_id)


@router.patch("/{rule_id}")
async def update_rule(rule_id: str, patch: RulePatch, s: SessionDep, svc: ServicesDep) -> Rule:
    return await RuleService(s, svc.sync).update(rule_id, patch)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, s: SessionDep, svc: ServicesDep) -> None:
    await RuleService(s, svc.sync).delete(rule_id)
