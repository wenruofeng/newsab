"""§4.4.1 invariants and the §3.3 S6 constrained-selection check.

The selection constraints describe the *shape* a good angle set has: not five ways of
saying one thing, not five findings of one type.  They are evaluated in code so the shape
is measured rather than asserted, and the measurements go into a ``constraint_report``
that ships in the manifest (§4.4.1 invariant 3).

**They are reported, not enforced** (D22).  The motive
was right and the instrument was wrong: shape was being measured by counting
``angle_type`` label strings, which measures an incidental reading→type mapping rather
than the diversity a reader would perceive.  A mis-measured gate does not produce better
angle sets, it produces relabelling to get past the gate.  So the statistics and
constraint layers emit a *signal*; whether a set ships is decided by a human at G2.

The one thing still fatal here is structural integrity — a selected angle that never went
through semantic clustering (``all_selected_are_clustered``), which is a broken artifact
rather than an editorial judgement.  Two hard rules live outside this module: a blind-spot
angle that fails the opportunity-to-cover check does not appear at all, and fewer than
three angles means going back for another round rather than lowering a threshold in place
(runbook §5).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

from ..enums import AngleStatus, AngleType
from ..models.analysis import CandidateAngle
from .report import ValidationReport

# The four yardsticks below are editorial goals, not gates (D22).  They stay module
# constants because a report item still needs a ruler: "6 angles" only means something
# against "the target is 5–8".  Read them as the shape S6 aims at, not as pass/fail lines.
#: §3.3 S6: the final set aims at 5–8 angles.
SELECTION_SIZE = (5, 8)
#: Angle types that count as "a voice or actor angle" for the goal.
VOICE_ACTOR_TYPES = {AngleType.VOICE_STRUCTURE, AngleType.ACTOR_ROLE}
#: Target ceiling on angles drawn from one semantic cluster, so the set is not paraphrases.
MAX_PER_SEMANTIC_CLUSTER = 2
#: Target minimum number of distinct angle types the set spans.
MIN_DISTINCT_TYPES = 3


@dataclass
class ConstraintResult:
    name: str
    #: Whether the run may proceed.  For editorial goals (D22) this is always ``True``;
    #: only structural integrity can make it ``False``.
    satisfied: bool
    detail: str
    #: Angles carrying this constraint, so ``selection.constraint_roles`` can be checked.
    contributors: list[str] = field(default_factory=list)
    #: For editorial goals: whether the goal was actually met, separately from whether the
    #: run may proceed.  ``None`` on rows where the two are the same thing.  G2 reads this;
    #: nothing branches on it.
    goal_met: Optional[bool] = None


@dataclass
class ConstraintReport:
    """What §4.4.1 invariant 3 requires be written into the manifest."""

    topic_id: str
    shortlisted: list[str]
    results: list[ConstraintResult]

    @property
    def satisfied(self) -> bool:
        return all(r.satisfied for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "shortlisted": self.shortlisted,
            "satisfied": self.satisfied,
            "results": [asdict(r) for r in self.results],
        }

    def failures(self) -> list[str]:
        return [r.name for r in self.results if not r.satisfied]

    def unmet_goals(self) -> list[str]:
        """Editorial goals the set did not reach.  Informational — see D22."""
        return [r.name for r in self.results if r.goal_met is False]


def check_selection_constraints(
    angles: Sequence[CandidateAngle], topic_id: str
) -> ConstraintReport:
    """Evaluate §3.3 S6's constrained selection over the shortlisted/approved set.

    Objective is information maximisation, not conflict maximisation — the goals below all
    describe a set that carries more than one kind of information.  Per D22 they are
    measured and reported, never enforced; ``goal_met`` on each row carries the verdict G2
    reads, and ``satisfied`` carries only "may this run proceed".
    """
    selected = [
        a
        for a in angles
        if a.selection.status in (AngleStatus.SHORTLISTED, AngleStatus.G2_APPROVED)
    ]
    ids = [a.angle_id for a in selected]
    results: list[ConstraintResult] = []

    low, high = SELECTION_SIZE
    in_range = low <= len(selected) <= high
    results.append(
        ConstraintResult(
            "set_size",
            True,
            f"{len(selected)} angles selected; §3.3 S6 aims at {low}–{high} — "
            + ("met" if in_range else "not met"),
            ids,
            goal_met=in_range,
        )
    )

    # R-8: the first row to be downgraded from a hard constraint to an editorial
    # goal, and the template the rest followed under D22.  With current corpus sizes
    # statistical consensus is structurally unreachable (G-5) — its evidence comes from the
    # concept map — so a run must not fail for lacking it.  The full data layer ships
    # regardless, so "no shared-ground angle" never means "no shared-ground data
    # published".  The result row stays so G2 sees whether the goal was met.
    shared = [
        a.angle_id
        for a in selected
        if a.angle_type in (AngleType.SHARED_GROUND, AngleType.CO_SILENCE)
    ]
    results.append(
        ConstraintResult(
            "shared_ground_editorial_goal",
            True,
            f"{len(shared)} shared_ground/co_silence angle(s); the editorial goal is ≥1 — "
            + ("met" if shared else "not met (expected under G-5; see the concept map)"),
            shared,
            goal_met=bool(shared),
        )
    )

    types = {a.angle_type for a in selected}
    enough_types = len(types) >= MIN_DISTINCT_TYPES
    results.append(
        ConstraintResult(
            "covers_min_distinct_types",
            True,
            f"{len(types)} distinct angle types ({sorted(t.value for t in types)}); "
            f"the editorial goal is ≥{MIN_DISTINCT_TYPES} — "
            + ("met" if enough_types else "not met"),
            ids,
            goal_met=enough_types,
        )
    )

    # This row is where the label-string problem is most visible — whether a finding
    # reads as "voice structure" depends on which reading the R-gate assigned it, not on
    # whether the set actually tells the reader who is speaking.  Reported, never enforced.
    voice = [a.angle_id for a in selected if a.angle_type in VOICE_ACTOR_TYPES]
    results.append(
        ConstraintResult(
            "at_least_one_voice_or_actor",
            True,
            f"{len(voice)} voice/actor angle(s); the editorial goal is ≥1 — "
            + ("met" if voice else "not met (a count of type labels, not a measure of who is heard)"),
            voice,
            goal_met=bool(voice),
        )
    )

    clusters: dict[str, list[str]] = {}
    for a in selected:
        key = a.semantic_cluster_id or f"<unclustered:{a.angle_id}>"
        clusters.setdefault(key, []).append(a.angle_id)
    overfull = {k: v for k, v in clusters.items() if len(v) > MAX_PER_SEMANTIC_CLUSTER}
    results.append(
        ConstraintResult(
            "max_per_semantic_cluster",
            True,
            (
                f"clusters over the target ceiling of {MAX_PER_SEMANTIC_CLUSTER}: {overfull} "
                "— not met"
                if overfull
                else f"no semantic cluster contributes more than {MAX_PER_SEMANTIC_CLUSTER} — met"
            ),
            [aid for group in overfull.values() for aid in group],
            goal_met=not overfull,
        )
    )

    # The one row that still fails a run (D22).  It is not an editorial judgement about the
    # shape of the set: an angle with no semantic_cluster_id never went through the
    # clustering step, so the "≤2 per cluster" reading above cannot even be computed for it
    # and the artifact is incomplete rather than merely unshapely.
    unclustered = [a.angle_id for a in selected if a.semantic_cluster_id is None]
    results.append(
        ConstraintResult(
            "all_selected_are_clustered",
            not unclustered,
            (
                f"selected angles never went through semantic clustering: {unclustered}"
                if unclustered
                else "every selected angle carries a semantic_cluster_id"
            ),
            unclustered,
        )
    )

    return ConstraintReport(topic_id=topic_id, shortlisted=ids, results=results)


def validate_angles(
    angles: Sequence[CandidateAngle],
    topic_id: str,
    *,
    known_observation_ids: Optional[Iterable[str]] = None,
    recompute: Optional[Callable[[CandidateAngle], dict[str, Optional[float]]]] = None,
    tolerance: float = 1e-9,
) -> ValidationReport:
    """Run every §4.4.1 invariant over a topic's candidate angles.

    ``recompute`` is the A1 hook for invariant 1: pass ``newsab_a1.recompute_metrics`` and
    every published number is re-derived from the feature matrix rather than trusted.
    Without it the check degrades to a warning, and says so — a silent skip here would
    defeat the entire submission-review model (AGENTS.md §7).
    """
    report = ValidationReport()
    known_obs = set(known_observation_ids) if known_observation_ids is not None else None
    seen: set[str] = set()
    alive = {a.angle_id for a in angles}

    for angle in angles:
        target = angle.angle_id
        if angle.angle_id in seen:
            report.error("duplicate_angle_id", target, "angle_id used twice")
        seen.add(angle.angle_id)

        if angle.topic_id != topic_id:
            report.error(
                "wrong_topic", target, f"angle belongs to topic {angle.topic_id}, not {topic_id}"
            )

        if angle.merged_into and angle.merged_into not in alive:
            report.error(
                "merged_into_unknown",
                target,
                f"merged_into={angle.merged_into} is not an angle in this set",
            )

        # Invariant 4 — exceptions must be a real answer, not a placeholder.
        if not angle.exceptions:
            report.info(
                "no_exceptions_recorded",
                target,
                "exceptions is empty — the judge must spot-check that there really are no "
                "counter-examples (§4.4.1 invariant 4)",
            )

        if known_obs is not None:
            for ref, kind in (
                [(o, "supporting_observations") for o in angle.supporting_observations]
                + [(o, "exceptions") for o in angle.exceptions]
            ):
                if ref not in known_obs:
                    report.error(
                        "unknown_observation_ref",
                        target,
                        f"{kind} references {ref}, which is not in the observation set",
                    )

        # Invariant 2 is enforced in the model for shortlisted angles; report the softer
        # case here so a failing blind-spot candidate is visible rather than merely absent.
        if angle.angle_type == AngleType.BLIND_SPOT and angle.blind_spot_check is not None:
            failed = angle.blind_spot_check.failed()
            if failed:
                report.info(
                    "blind_spot_conditions_failed",
                    target,
                    f"blind-spot conditions not met: {failed}; this angle cannot be published "
                    "and may only be downgraded to a sample-composition note (§3.3 S6)",
                )

        # Invariant 1 — every metric recomputable from a1_run_id.
        if recompute is None:
            report.warning(
                "metrics_not_recomputed",
                target,
                "no recompute hook supplied; metrics were taken on trust",
                "pass newsab_a1.recompute_metrics so §4.4.1 invariant 1 is actually checked",
            )
        else:
            try:
                expected = recompute(angle)
            except (KeyError, ValueError, OSError) as exc:
                report.error(
                    "metric_recompute_failed",
                    target,
                    str(exc),
                    "use the exact immutable A1 run named by metrics.a1_run_id",
                )
                continue
            actual = {
                "delta": angle.metrics.delta.value,
                "delta_lo": angle.metrics.delta.lo,
                "delta_hi": angle.metrics.delta.hi,
                "direction_stability": angle.metrics.direction_stability,
                "conservative_effect": angle.metrics.conservative_effect,
                "log_odds": angle.metrics.log_odds,
            }
            for group in angle.comparison.groups:
                actual[f"clusters_supporting.{group.group_id}"] = float(
                    group.clusters_supporting
                )
                actual[f"clusters_total.{group.group_id}"] = float(group.clusters_total)
                actual[f"prevalence.{group.group_id}"] = (
                    angle.metrics.prevalence.by_group.get(group.group_id)
                )
                actual[f"concentration.{group.group_id}"] = (
                    angle.metrics.concentration.by_group.get(group.group_id)
                )
                for category, count in group.by_category.items():
                    if count is None:
                        continue
                    actual[f"by_category_supporting.{group.group_id}.{category}"] = float(
                        count.supporting
                    )
                    actual[f"by_category_total.{group.group_id}.{category}"] = float(
                        count.total
                    )
            for key, want in expected.items():
                got = actual.get(key)
                if want is None:
                    if got is not None:
                        report.error(
                            "metric_recompute_mismatch",
                            target,
                            f"{key}: stored {got!r}, recomputed an absent denominator",
                        )
                    continue
                if got is None:
                    report.error(
                        "metric_recompute_missing",
                        target,
                        f"{key}: recomputed {want!r} but the angle does not record it",
                    )
                    continue
                if abs(got - want) > tolerance:
                    report.error(
                        "metric_recompute_mismatch",
                        target,
                        f"{key}: stored {got!r}, recomputed {want!r} from "
                        f"a1_run_id={angle.metrics.a1_run_id}",
                        "artifacts are immutable — re-run A1 and emit a new angle version "
                        "rather than editing the number",
                    )

    constraint_report = check_selection_constraints(angles, topic_id)
    report.stats["constraint_report"] = constraint_report.to_dict()
    for result in constraint_report.results:
        if not result.satisfied:
            report.error("selection_constraint_failed", result.name, result.detail)
        elif result.goal_met is False:
            # D22: an unmet editorial goal is something G2 should see and weigh, not
            # something that stops the run.  It is a warning so it survives into the
            # rendered report, and `strict` callers can still choose to treat it as fatal.
            report.warning(
                "selection_goal_unmet",
                result.name,
                result.detail,
                "an editorial goal, not a gate (D22) — G2 decides whether the set ships",
            )

    # §4.4.1 invariant 3's other half: declared roles must match reality.
    for angle in angles:
        if angle.selection.status not in (AngleStatus.SHORTLISTED, AngleStatus.G2_APPROVED):
            continue
        for role in angle.selection.constraint_roles:
            if role.startswith("covers_type:"):
                claimed = role.split(":", 1)[1]
                if claimed != angle.angle_type.value:
                    report.error(
                        "constraint_role_mismatch",
                        angle.angle_id,
                        f"claims role {role!r} but angle_type is {angle.angle_type.value}",
                    )

    report.stats["angles"] = len(angles)
    report.stats["shortlisted"] = len(constraint_report.shortlisted)
    return report
