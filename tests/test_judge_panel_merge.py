"""The judge panel: multi-judge merge, and churn defined on rewritten text only.

The stage's stop condition used to be prose ("more new defects than last round, in
sections that previously passed"), and two real runs showed it pointing both ways: one
run's later rounds found true defects on untouched text (the rule said stop, stopping
would have lost them), another's round four re-scored byte-identical text (the rule said
keep going).
The rule is now arithmetic — a fault is churn only when it is new *and* lands on a locus
the fix pass rewrote — so it is tested here rather than argued in the run report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.cli_e2e

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "skills" / "render-localize" / "scripts" / "check_judge.py"

AXES = (
    "evidence_entailment",
    "symmetry",
    "silence_and_strength",
    "scope_discipline",
    "overall_impression",
)


def judge(rubric: str = "rl-judge-0.4", **faults: tuple[int, str]) -> dict:
    """A judge document scoring 2 everywhere except the axes named in ``faults``."""
    scores = {axis: {"score": 2, "note": "clean", "refs": []} for axis in AXES}
    for axis, (score, ref) in faults.items():
        scores[axis] = {"score": score, "note": f"fault at {ref}", "refs": [ref]}
    return {
        "rubric_version": rubric,
        "scores": scores,
        "unverified_readings": [],
        "contradicted_notes": [],
    }


def page(**angle_texts: str) -> dict:
    """A page stub whose angle bodies are whatever the test wants to (not) rewrite."""
    return {
        "topic_id": "t",
        "title": {"values": {"en": "T"}},
        "intro": [],
        "angles": [
            {
                "rank": int(name.removeprefix("a")),
                "question_id": f"QST-t-00{name.removeprefix('a')}",
                "finding_id": f"FND-t-00{name.removeprefix('a')}-divergence",
                "sides": [{"answer": {"text": {"values": {"en": text}}}}],
            }
            for name, text in sorted(angle_texts.items())
        ],
        "provenance": {"run_id": "rl-whatever"},
    }


def write(tmp_path: Path, name: str, doc: dict) -> Path:
    path = tmp_path / name
    if "angles" not in doc:  # a judge doc: keep panel members byte-distinct
        doc = dict(doc, pass_id=name)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), *(str(a) for a in args)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def panel_args(*paths: Path, model: str = "m-standard") -> list[object]:
    out: list[object] = []
    for path in paths:
        out += ["--judge", path]
    return out + ["--judge-model", model]


def test_clean_panel_passes_and_records_every_member(tmp_path):
    judges = [write(tmp_path, f"j{i}.json", judge()) for i in range(3)]
    out = tmp_path / "panel.json"
    result = run(*panel_args(*judges), "--out", out)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["verdict"] == "clean"
    assert record["panel_size"] == 3
    assert [j["model"] for j in record["judges"]] == ["m-standard"] * 3
    assert record["findings"] == []


def test_merge_takes_the_union_so_one_judges_fault_survives_two_passes(tmp_path):
    # The whole point of the panel: a defect two judges missed is still a defect.  Two
    # different single 1s from two different judges are two 1s on the merged record,
    # which is the "two or more scores of 1" trigger.
    judges = [
        write(tmp_path, "j1.json", judge(symmetry=(1, "angle 3"))),
        write(tmp_path, "j2.json", judge(scope_discipline=(1, "angle 2"))),
        write(tmp_path, "j3.json", judge()),
    ]
    out = tmp_path / "panel.json"
    result = run(*panel_args(*judges), "--out", out)
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["scores"]["symmetry"]["score"] == 1
    assert record["scores"]["scope_discipline"]["score"] == 1
    assert record["scores"]["evidence_entailment"]["score"] == 2
    assert any("judge_two_ones" in line for line in record["escalations"])
    located = {(f["kind"], f["locus"], f["agreement"]) for f in record["findings"]}
    assert located == {
        ("axis:symmetry", "angle 3", "1/3"),
        ("axis:scope_discipline", "angle 2", "1/3"),
    }


def test_blocking_lists_union_and_dedup_across_judges(tmp_path):
    a = judge()
    a["unverified_readings"] = ["angle 1 reading"]
    b = judge()
    b["unverified_readings"] = ["angle 1 reading", {"ref": "angle 4 reading"}]
    judges = [
        write(tmp_path, "j1.json", a),
        write(tmp_path, "j2.json", b),
        write(tmp_path, "j3.json", judge()),
    ]
    out = tmp_path / "panel.json"
    result = run(*panel_args(*judges), "--out", out)
    assert result.returncode == 1
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["unverified_readings"] == ["angle 1 reading", "angle 4 reading"]
    agreement = {
        f["locus"]: f["agreement"]
        for f in record["findings"]
        if f["kind"] == "unverified_readings"
    }
    assert agreement == {"angle 1": "2/3", "angle 4": "1/3"}


def test_a_panel_of_one_is_refused_as_the_serial_flow(tmp_path):
    only = write(tmp_path, "j1.json", judge())
    result = run(*panel_args(only))
    assert result.returncode == 2
    assert "--panel-min" in result.stderr
    assert run(*panel_args(only), "--panel-min", 1).returncode == 0


def test_mixed_rubric_versions_are_unusable_input(tmp_path):
    judges = [
        write(tmp_path, "j1.json", judge()),
        write(tmp_path, "j2.json", judge()),
        write(tmp_path, "j3.json", judge(rubric="rl-judge-0.3")),
    ]
    result = run(*panel_args(*judges))
    assert result.returncode == 2
    assert "rubric" in result.stderr


def test_model_ids_must_be_one_or_one_per_judge(tmp_path):
    judges = [write(tmp_path, f"j{i}.json", judge()) for i in range(3)]
    args: list[object] = []
    for path in judges:
        args += ["--judge", path]
    two = run(*args, "--judge-model", "a", "--judge-model", "b")
    assert two.returncode == 2 and "--judge-model" in two.stderr
    three = run(
        *args, "--judge-model", "a", "--judge-model", "b", "--judge-model", "c"
    )
    assert three.returncode == 0, three.stdout + three.stderr


def _round_one(tmp_path: Path, before: dict) -> Path:
    judges = [
        write(tmp_path, "r1j1.json", judge(symmetry=(1, "angle 2"))),
        write(tmp_path, "r1j2.json", judge(evidence_entailment=(1, "angle 2"))),
        write(tmp_path, "r1j3.json", judge()),
    ]
    out = tmp_path / "panel1.json"
    result = run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page1.json", before),
        "--out",
        out,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    return out


def test_new_fault_on_rewritten_text_is_churn_and_stops_the_loop(tmp_path):
    before = page(a1="one", a2="two", a3="three")
    panel1 = _round_one(tmp_path, before)
    after = page(a1="one", a2="two, fixed", a3="three")  # only angle 2 rewritten
    judges = [
        write(tmp_path, "r2j1.json", judge(scope_discipline=(0, "angle 2"))),
        write(tmp_path, "r2j2.json", judge()),
    ]
    out = tmp_path / "panel2.json"
    result = run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page2.json", after),
        "--previous",
        panel1,
        "--out",
        out,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["round"] == 2
    assert record["rewritten_loci"] == ["angle 2"]
    assert record["verdict"] == "stop"
    churn = [f for f in record["findings"] if f["classification"] == "churn"]
    assert [(f["kind"], f["locus"]) for f in churn] == [
        ("axis:scope_discipline", "angle 2")
    ]


def test_a_repeated_fault_on_rewritten_text_is_persistent_not_churn(tmp_path):
    before = page(a1="one", a2="two", a3="three")
    panel1 = _round_one(tmp_path, before)
    after = page(a1="one", a2="two, fixed", a3="three")
    # Even a *worse* score on rewritten text is not churn when it is the same axis on
    # the same locus: the fix did not land (or was refused with a reason), which is a
    # different situation from the fix breaking something that was fine.
    judges = [
        write(tmp_path, "r2j1.json", judge(symmetry=(0, "angle 2"))),
        write(tmp_path, "r2j2.json", judge(symmetry=(0, "angle 2"))),
    ]
    out = tmp_path / "panel2.json"
    result = run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page2.json", after),
        "--previous",
        panel1,
        "--out",
        out,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert [f["classification"] for f in record["findings"]] == ["persistent"]


def test_new_fault_on_untouched_text_is_recall_variance_not_churn(tmp_path):
    # The observed case: a later pass reports a true defect in a paragraph nobody edited.
    before = page(a1="one", a2="two", a3="three")
    panel1 = _round_one(tmp_path, before)
    after = page(a1="one", a2="two, fixed", a3="three")
    judges = [
        write(tmp_path, "r2j1.json", judge(scope_discipline=(0, "angle 3"))),
        write(tmp_path, "r2j2.json", judge()),
    ]
    out = tmp_path / "panel2.json"
    result = run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page2.json", after),
        "--previous",
        panel1,
        "--out",
        out,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert [f["classification"] for f in record["findings"]] == ["recall"]


def test_findings_can_be_located_by_the_finding_id_a_judge_cites(tmp_path):
    judges = [
        write(tmp_path, "j1.json", judge(symmetry=(1, "FND-t-002-divergence"))),
        write(tmp_path, "j2.json", judge(symmetry=(1, "QST-t-002"))),
        write(tmp_path, "j3.json", judge()),
    ]
    out = tmp_path / "panel.json"
    run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page.json", page(a1="one", a2="two")),
        "--out",
        out,
    )
    record = json.loads(out.read_text(encoding="utf-8"))
    assert [(f["kind"], f["locus"], f["agreement"]) for f in record["findings"]] == [
        ("axis:symmetry", "angle 2", "2/3")
    ]


def test_churn_check_refuses_to_guess_which_text_was_rewritten(tmp_path):
    before = page(a1="one", a2="two")
    panel1 = _round_one(tmp_path, before)
    judges = [write(tmp_path, f"r2j{i}.json", judge()) for i in range(2)]
    result = run(*panel_args(*judges), "--previous", panel1)
    assert result.returncode == 2
    assert "--page" in result.stderr


def test_the_panel_budget_turns_a_third_escalation_into_a_human_decision(tmp_path):
    judges = [
        write(tmp_path, "j1.json", judge(symmetry=(0, "angle 1"))),
        write(tmp_path, "j2.json", judge()),
    ]
    out = tmp_path / "panel3.json"
    result = run(*panel_args(*judges), "--round", 3, "--out", out)
    assert result.returncode == 3, result.stdout + result.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "stop"


def test_a_copied_pass_and_an_unlocated_fault_are_both_flagged(tmp_path):
    doc = json.dumps(judge(symmetry=(1, "the second paragraph")), ensure_ascii=False)
    judges = []
    for name in ("j1.json", "j2.json", "j3.json"):
        (tmp_path / name).write_text(doc, encoding="utf-8")
        judges.append(tmp_path / name)
    result = run(*panel_args(*judges))
    # Three members at 1 on the same axis is a consensus trigger since panel 0.2.
    assert result.returncode == 1
    assert "judge_consensus_one" in result.stdout
    assert "byte-identical" in result.stdout
    assert "name no page locus" in result.stdout


def test_a_lone_members_score_of_one_is_variance_not_a_trigger(tmp_path):
    judges = [
        write(tmp_path, "j1.json", judge(symmetry=(1, "the second paragraph"))),
        write(tmp_path, "j2.json", judge()),
        write(tmp_path, "j3.json", judge()),
    ]
    result = run(*panel_args(*judges))
    assert result.returncode == 0, result.stdout + result.stderr


def test_two_members_scoring_the_same_axis_one_escalate(tmp_path):
    # Observed: two of three judges independently faulted entailment on the same angles and
    # the page still shipped — the trigger this test pins closes that gap.
    judges = [
        write(tmp_path, "j1.json", judge(evidence_entailment=(1, "angle 1"))),
        write(tmp_path, "j2.json", judge(evidence_entailment=(1, "angle 3"))),
        write(tmp_path, "j3.json", judge()),
    ]
    out = tmp_path / "panel.json"
    result = run(*panel_args(*judges), "--out", out)
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert any("judge_consensus_one" in line for line in record["escalations"])
    assert not any("judge_two_ones" in line for line in record["escalations"])


def test_a_ref_reading_list_without_a_locating_note_is_unlocated_not_churn(tmp_path):
    """Pub run, 2026-09-01: a round hard-stopped on `evidence_entailment / angle 1`
    though no member had written a defect for angle 1 — the locus was parsed out of a
    refs list that carried no defect statement, and angle 1 happened to be rewritten.
    A bag of refs under a note that locates nothing is a reading list, not N located
    defects; it belongs in the unlocated bucket panel.md routes to manual triage."""
    before = page(a1="one", a2="two", a3="three")
    panel1 = _round_one(tmp_path, before)
    after = page(a1="one, polished", a2="two, fixed", a3="three")
    faulty = judge()
    faulty["scores"]["evidence_entailment"] = {
        "score": 0,
        "note": "one summary overstates what its anchor supports",
        "refs": ["angle 1", "angle 2", "angle 3"],
    }
    judges = [
        write(tmp_path, "r2j1.json", faulty),
        write(tmp_path, "r2j2.json", judge()),
    ]
    out = tmp_path / "panel2.json"
    result = run(
        *panel_args(*judges),
        "--page",
        write(tmp_path, "page2.json", after),
        "--previous",
        panel1,
        "--out",
        out,
    )
    record = json.loads(out.read_text(encoding="utf-8"))
    assert result.returncode != 3, result.stdout + result.stderr
    assert record["verdict"] != "stop"
    entailment = [f for f in record["findings"] if f["kind"] == "axis:evidence_entailment"]
    assert [f["locus"] for f in entailment] == [""]
    assert [f["classification"] for f in entailment] == ["unlocated"]


def test_a_single_ref_still_locates_a_note_that_names_no_locus(tmp_path):
    # The legitimate division of labour — note describes the defect, one ref points at
    # it — keeps working, including the `{"angle": N}` object shape a verbose judge uses.
    faulty = judge()
    faulty["scores"]["symmetry"] = {
        "score": 0,
        "note": "the anchor does not support the claim",
        "refs": [{"angle": 3}],
    }
    judges = [
        write(tmp_path, "j1.json", faulty),
        write(tmp_path, "j2.json", judge()),
        write(tmp_path, "j3.json", judge()),
    ]
    out = tmp_path / "panel.json"
    result = run(*panel_args(*judges), "--out", out)
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    symmetry = [f for f in record["findings"] if f["kind"] == "axis:symmetry"]
    assert [f["locus"] for f in symmetry] == ["angle 3"]


def test_a_score_outside_the_rubric_is_unusable_input(tmp_path):
    bad = judge()
    bad["scores"]["symmetry"]["score"] = 5
    judges = [
        write(tmp_path, "j1.json", judge()),
        write(tmp_path, "j2.json", judge()),
        write(tmp_path, "j3.json", bad),
    ]
    result = run(*panel_args(*judges))
    assert result.returncode == 2
    assert "outside 0/1/2" in result.stderr
