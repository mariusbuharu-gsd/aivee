"""evals/vision: the label matcher and the runner's empty case (no models, no clips)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from aivee_contracts.rules import Action, Condition, Rule

EVALS = Path(__file__).resolve().parents[3] / "evals" / "vision"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"eval_vision_{name}", EVALS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


m = _load("matcher")


def test_matcher_scores_hits_misses_repeats_and_false_alerts() -> None:
    labels = m.ClipLabels.from_json(
        {
            "expected": [
                {"kind": "raised_hand", "zone": "t1", "t_start": 30, "t_end": 40},
                {"kind": "raised_hand", "zone": "t2", "t_start": 100, "t_end": 110},
                {"kind": "unattended", "t_start": 300, "t_end": 400},
            ],
            "tolerance_s": 5,
        }
    )
    produced = [
        m.Produced("raised_hand", "t1", 36.0),  # hit
        m.Produced("raised_hand", "t1", 38.0),  # same window again: repeat
        m.Produced("raised_hand", "t1", 70.0),  # nothing expected: false
        m.Produced("raised_hand", "t2", 96.0),  # 4 s early, within tolerance: hit
        m.Produced("not_cleared", "t1", 320.0),  # wrong kind: false
    ]
    result = m.match(labels, produced, duration_s=1800.0)
    assert [p.t for _, p in result.hits] == [36.0, 96.0]
    assert [e.kind for e in result.misses] == ["unattended"]
    assert [p.t for p in result.repeats] == [38.0]
    assert [p.t for p in result.false_alerts] == [70.0, 320.0]

    summary = m.summarise([result])
    assert summary.by_kind["raised_hand"].recall == 1.0
    assert summary.by_kind["unattended"].recall == 0.0
    assert summary.false_alerts == 2 and summary.false_per_hour() == pytest.approx(4.0)
    assert "raised_hand" in m.report(summary)


def test_partly_labelled_clips_judge_only_quiet_segments() -> None:
    labels = m.ClipLabels.from_json(
        {"fully_labelled": False, "quiet": [{"t_start": 0, "t_end": 900}]}
    )
    produced = [m.Produced("raised_hand", "t1", 100.0), m.Produced("raised_hand", "t1", 1000.0)]
    result = m.match(labels, produced, duration_s=1800.0)
    assert [p.t for p in result.false_alerts] == [100.0]
    assert [p.t for p in result.unjudged] == [1000.0]
    assert result.labelled_s == 900.0


def test_unknown_kind_in_labels_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        m.ClipLabels.from_json({"expected": [{"kind": "hand", "t_start": 0, "t_end": 1}]})


def _rule(*conds: Condition) -> Rule:
    return Rule(
        id="r",
        camera_id="c",
        name="n",
        prompt_ro="p",
        zone_tag="table",
        all_of=list(conds),
        action=Action(type="telegram"),
    )


def test_rule_kind_follows_the_most_specific_condition() -> None:
    present = Condition(kind="present", role="guest", min_duration_s=60)
    absent = Condition(kind="absent", role="staff", min_duration_s=300)
    hand = Condition(kind="pose", role="guest", pose="raised_hand")
    assert m.rule_kind(_rule(present, absent)) == "unattended"
    assert m.rule_kind(_rule(hand)) == "raised_hand"


def test_default_rules_cover_the_table_situations() -> None:
    run = _load("run")
    kinds = {m.rule_kind(r) for r in run.load_rules(None, "cam-01")}
    assert {"unattended", "raised_hand", "not_cleared", "queue"} <= kinds


def test_runner_is_green_on_zero_clips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _load("run")
    assert run.main(["--clips", str(tmp_path)]) == 0
    assert "no labelled clips" in capsys.readouterr().out
