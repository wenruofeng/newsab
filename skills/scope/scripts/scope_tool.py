#!/usr/bin/env python3
"""Deterministic support for the scope sitting: skeleton, checks, and approval.

    init      write a minimal topic_manifest.yaml + scope/collection_plan.md skeleton
    apply-question-review
              copy only approved candidate questions into the manifest, enforcing that
              an LLM stand-in cannot mark one required
    check     validate the draft; print the scope hash and everything the user is
              about to approve; lint both artifacts for expected-finding language
    approve   AFTER the user's explicit word only: bind their approval to the exact
              current scope hash and set the topic active

    python skills/scope/scripts/scope_tool.py init <topics_root> <topic_id> \
        --title-en "…" --group cn:CN --group jp:JP --review-locale <bcp47> \
        [--model-id <model>]
    python skills/scope/scripts/scope_tool.py apply-question-review <topics_root> <topic_id> \
        --decided-by human
    python skills/scope/scripts/scope_tool.py check <topics_root> <topic_id>
    python skills/scope/scripts/scope_tool.py approve <topics_root> <topic_id> \
        --approved-by <name> --decided-by human [--note "…"]

Approval is never hand-assembled: an agent-typed ``active`` enum cannot pass the
touchpoint, and a hash typed by hand binds nothing.
Exit codes: 0 ok · 1 check failed / not approvable · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from newsab_schema.enums import GateDecider
from newsab_schema.io import ArtifactError, read_yaml, write_yaml
from newsab_schema.locales import HALO_LOCALE_CODES
from newsab_schema.models.corpus import QuestionSeed, TopicManifest
from newsab_schema.paths import TopicPaths

# Predictive phrasing that has no place in a scope artifact: the gate approves scope and
# risk, never a conclusion.
EXPECTED_FINDING = re.compile(
    r"we expect|expected finding|likely to find|will (?:probably )?(?:show|find|diverge)"
    r"|hypothes[ie]s|预期|预计发现|应该会发现|大概率发现",
    re.IGNORECASE,
)


def _skill_version() -> str:
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^\s*(?:newsab-)?version:\s*"?([0-9][\w.]*)"?\s*$', text, re.MULTILINE)
    if match is None:
        raise ArtifactError("skills/scope/SKILL.md has no parseable 'version:' line")
    return f"scope-{match.group(1)}"


SKELETON_PLAN = """# Collection plan — {topic_id}

## Window rationale
<why period.start is where it is, and why the window is answerable on BOTH sides>

## Per side
### {g0}
- search terms (that side's own language and namings): …
- candidate outlets ({g0}): name — category (serious/other) — beat_scope — in registry? channel known?
- channels shown to work for this language, or "unproven": …

### {g1}
- (same structure)

## Registry gaps
<outlets the collect stage will have to register from scratch>
"""

SKELETON_QUESTIONS = """# Scope-only review artifact. Annotate must never receive or read this file.
candidates: []
review_record: null
"""


def _questions_path(paths: TopicPaths) -> Path:
    return paths.root / "scope" / "question_candidates.yaml"


def _load_question_candidates(paths: TopicPaths) -> tuple[dict, list[str]]:
    path = _questions_path(paths)
    if not path.exists():
        return {}, [f"{path} is missing"]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {}, [f"{path}: invalid YAML: {exc}"]
    problems: list[str] = []
    if not isinstance(raw, dict):
        return {}, [f"{path}: top level must be a mapping"]
    candidates = raw.get("candidates")
    if not isinstance(candidates, list):
        return raw, [f"{path}: candidates must be a list"]
    seen: set[str] = set()
    for index, candidate in enumerate(candidates, 1):
        where = f"{path}: candidate {index}"
        if not isinstance(candidate, dict):
            problems.append(f"{where} must be a mapping")
            continue
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not re.fullmatch(r"SQ-[0-9]{3}", candidate_id):
            problems.append(f"{where}: candidate_id must match SQ-001")
        elif candidate_id in seen:
            problems.append(f"{where}: duplicate candidate_id {candidate_id}")
        else:
            seen.add(candidate_id)
        review = candidate.get("review")
        if not isinstance(review, dict):
            problems.append(f"{where}: review must carry approved/required checkmarks")
            continue
        approved = review.get("approved")
        required = review.get("required")
        if not isinstance(approved, bool) or not isinstance(required, bool):
            problems.append(f"{where}: review.approved and review.required must be booleans")
        elif required and not approved:
            problems.append(f"{where}: required cannot be checked unless approved is checked")
        if "text" not in candidate:
            problems.append(f"{where}: text is missing")
    return raw, problems


def _approved_seeds(raw: dict) -> tuple[list[QuestionSeed], list[str]]:
    seeds: list[QuestionSeed] = []
    problems: list[str] = []
    for index, candidate in enumerate(raw.get("candidates", []), 1):
        if not isinstance(candidate, dict) or not candidate.get("review", {}).get("approved"):
            continue
        payload = {
            "seed_id": candidate.get("candidate_id"),
            "text": candidate.get("text"),
            "mandate": (
                "required" if candidate.get("review", {}).get("required") else "reference"
            ),
        }
        try:
            seeds.append(QuestionSeed.model_validate(payload))
        except Exception as exc:
            problems.append(f"candidate {index}: {str(exc).replace(chr(10), ' ')[:400]}")
    return seeds, problems


def cmd_init(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if paths.topic_manifest.exists():
        print(f"refusing to overwrite existing {paths.topic_manifest}", file=sys.stderr)
        return 1
    # The reviewer's own language is a fact about *this* topic's sitting, asked for here
    # rather than defaulted: an agent that assumes its operator's language mislabels the
    # one record that says which rendering a human actually read.  It must be one of the
    # site's nine, because touchpoint two is a page the renderer has to be able to
    # produce in that language.
    review_locale = args.review_locale
    if review_locale not in HALO_LOCALE_CODES:
        print(
            f"--review-locale {review_locale!r} is not one of the site's nine languages: "
            f"{', '.join(HALO_LOCALE_CODES)}",
            file=sys.stderr,
        )
        return 2
    groups = []
    for spec in args.group:
        gid, _, prefix = spec.partition(":")
        if not prefix:
            print(f"--group must be <group_id>:<PREFIX>, got {spec!r}", file=sys.stderr)
            return 2
        groups.append({
            "group_id": gid, "prefix": prefix,
            "label": {"values": {"en": f"<full noun phrase for {gid}>"}},
            # Both languages the page will exist in at review time: the English pivot
            # and the reviewer's own.  Keyed by ``review_locale`` rather than a literal —
            # the same dict when the reviewer reads English, two entries otherwise.
            "short_label": {
                "values": {
                    "en": f"<{gid} side>",
                    **({} if review_locale == "en" else {review_locale: "<short noun, 2-4 words or characters>"}),
                }
            },
            "definition": {"values": {"en": f"<natural-language membership rule for {gid}>"}},
        })
    now = datetime.now(timezone.utc)
    manifest = {
        "topic_id": args.topic_id,
        "title": {"values": {"en": args.title_en}},
        "status": "candidate",
        "groups": groups,
        "period": {"start": str(date.today()), "end": None},
        "include": ["<who, what, which window — one specific line per sub-topic in scope>"],
        "exclude": ["<the adjacent thing a collector would otherwise sweep in>"],
        "risk_level": "medium",
        "seed_questions": [],
        "target_clusters_per_group": {g["group_id"]: 20 for g in groups},
        # Who answers for this topic.  The page record names them, and — unless a
        # stand-in is declared — they are also who signs scope and who takes the page
        # review.  An empty list publishes as "anonymous".
        "contributors": [{"name": name} for name in (args.contributor or [])],
        "review_stand_in_model_id": args.review_stand_in_model_id,
        # Which language touchpoint two is read and signed in.  Everything downstream
        # reads it from here — the localization floor a publication ships, which preview
        # the release card binds its approval hash to, which language the user's own
        # words on that card are recorded as.
        "review_locale": review_locale,
        "provenance": {
            "skill_version": _skill_version(),
            "model_id": args.model_id,
            "run_id": f"scope-{now:%Y%m%d%H%M%S%f}-{secrets.token_hex(4)}",
            "timestamp": now.isoformat(),
        },
    }
    paths.topic_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.topic_manifest.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    plan = paths.root / "scope" / "collection_plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    g_ids = [g["group_id"] for g in groups]
    plan.write_text(SKELETON_PLAN.format(topic_id=args.topic_id, g0=g_ids[0],
                                         g1=g_ids[1] if len(g_ids) > 1 else "…"),
                    encoding="utf-8")
    questions = _questions_path(paths)
    questions.write_text(SKELETON_QUESTIONS, encoding="utf-8")
    print(f"wrote {paths.topic_manifest}\nwrote {plan}\nwrote {questions}\n"
          "Fill every <placeholder>, then run check.")
    return 0


def cmd_apply_question_review(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    manifest = _load(paths)
    raw, problems = _load_question_candidates(paths)
    seeds, seed_problems = _approved_seeds(raw)
    problems.extend(seed_problems)
    decided_by = GateDecider(args.decided_by)
    if decided_by == GateDecider.LLM_STAND_IN:
        if not args.stand_in_model_id:
            problems.append("LLM stand-in review requires --stand-in-model-id")
        if any(seed.mandate.value == "required" for seed in seeds):
            problems.append(
                "LLM stand-in may approve reference questions only; "
                "uncheck required or wait for a human"
            )
    if problems:
        for problem in problems:
            print(f"problem: {problem}")
        print("NOT applied")
        return 1

    data = manifest.model_dump(mode="json", exclude_none=False)
    data["seed_questions"] = []
    data["question_seeds"] = [seed.model_dump(mode="json") for seed in seeds]
    # Applying a review is a scope change. Clear rather than merely stale the previous
    # approval so a human can replace an earlier stand-in review with required seeds.
    data["scope_approval"] = None
    data["status"] = "candidate"
    updated = TopicManifest.model_validate(data)
    write_yaml(paths.topic_manifest, updated)

    reviewed_at = datetime.now(timezone.utc).isoformat()
    raw["review_record"] = {
        "decided_by": decided_by.value,
        "decided_at": reviewed_at,
        "stand_in_model_id": args.stand_in_model_id,
    }
    _questions_path(paths).write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    required = sum(seed.mandate.value == "required" for seed in seeds)
    print(
        f"applied {len(seeds)} approved question seed(s): "
        f"{required} required, {len(seeds) - required} reference"
    )
    return 0


def _load(paths: TopicPaths) -> TopicManifest:
    return read_yaml(paths.topic_manifest, TopicManifest)


def cmd_check(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.topic_manifest.exists():
        print(f"no topic manifest: {paths.topic_manifest}", file=sys.stderr)
        return 2
    try:
        manifest = _load(paths)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    problems: list[str] = []
    raw = paths.topic_manifest.read_text(encoding="utf-8")
    if "<" in raw and ">" in raw:
        problems.append("manifest still contains <placeholder> text")
    plan = paths.root / "scope" / "collection_plan.md"
    if not plan.exists():
        problems.append("scope/collection_plan.md is missing")
        plan_text = ""
    else:
        plan_text = plan.read_text(encoding="utf-8")
        if "<" in plan_text and ">" in plan_text:
            problems.append("collection plan still contains <placeholder> text")
    for name, text in [("manifest", raw), ("collection plan", plan_text)]:
        hit = EXPECTED_FINDING.search(text)
        if hit:
            problems.append(f"{name} contains expected-finding language: {hit.group(0)!r} "
                            "— the gate approves scope and risk, never a conclusion")
    for g in manifest.groups:
        for field in ("label", "short_label", "definition"):
            if not getattr(g, field).values:
                problems.append(f"group {g.group_id}: {field} is empty")
    for line in manifest.include:
        if len(line.split()) < 4:
            problems.append(f"include line too vague to collect against: {line!r}")
    # Not part of the hash the user signs, but the sitting is where it is knowable:
    # after this gate no stage may guess it, and one that has to guess picks the agent's
    # own language instead of the reviewer's.
    if not manifest.review_locale:
        problems.append(
            "topic_manifest.review_locale is unset: name the language touchpoint two "
            "will be read and signed in (one of " + ", ".join(HALO_LOCALE_CODES) + ")"
        )
    elif manifest.review_locale not in HALO_LOCALE_CODES:
        problems.append(
            f"topic_manifest.review_locale {manifest.review_locale!r} is not one of the "
            "site's nine languages: " + ", ".join(HALO_LOCALE_CODES)
        )

    candidates_path = _questions_path(paths)
    if candidates_path.exists():
        candidate_raw, candidate_problems = _load_question_candidates(paths)
        problems.extend(candidate_problems)
        expected_seeds, seed_problems = _approved_seeds(candidate_raw)
        problems.extend(seed_problems)
        review_record = candidate_raw.get("review_record")
        if not isinstance(review_record, dict):
            problems.append(
                "question candidate checkmarks have not been applied; run apply-question-review"
            )
        else:
            try:
                decider = GateDecider(review_record.get("decided_by"))
            except Exception:
                problems.append("question review_record.decided_by is invalid")
                decider = None
            if decider == GateDecider.LLM_STAND_IN:
                if not review_record.get("stand_in_model_id"):
                    problems.append("LLM question review is missing stand_in_model_id")
                if any(seed.mandate.value == "required" for seed in expected_seeds):
                    problems.append("LLM question review cannot create required seeds")
        actual = [seed.model_dump(mode="json") for seed in manifest.question_seeds]
        expected = [seed.model_dump(mode="json") for seed in expected_seeds]
        if actual != expected:
            problems.append(
                "topic_manifest.question_seeds does not match the approved checkmarks; "
                "run apply-question-review"
            )

    print(f"topic   {manifest.topic_id} — status {manifest.status.value}")
    print(f"period  {manifest.period.start} .. {manifest.period.end or 'open'}")
    for g in manifest.groups:
        print(f"group   {g.group_id} ({g.prefix}) — {g.definition.get('en') or ''}")
    print(f"include {len(manifest.include)} line(s) · exclude {len(manifest.exclude)} · "
          f"risk {manifest.risk_level.value} · targets {manifest.target_clusters_per_group}")
    if manifest.question_seeds:
        required = sum(seed.mandate.value == "required" for seed in manifest.question_seeds)
        print(
            f"questions {len(manifest.question_seeds)} approved · "
            f"{required} required · {len(manifest.question_seeds) - required} reference"
        )
    elif manifest.seed_questions:
        print(f"questions {len(manifest.seed_questions)} legacy reference-only seed text(s)")
    else:
        print("questions 0 approved")
    # Outside the hash, but the user still has to see it: it is the only line on the
    # published page record that names a human.
    people = " · ".join(c.name or "anonymous" for c in manifest.contributors) or "anonymous"
    review = manifest.review_stand_in_model_id
    print(
        f"people  contributor(s) {people} · touchpoint two "
        + (f"{review} (AI stand-in)" if review else "human")
        + f" · reads {manifest.review_locale or '(unset)'}"
    )
    print(f"scope_hash {manifest.scope_hash()}")
    for p in problems:
        print(f"problem: {p}")
    print("ok — ready for the user's word" if not problems else "NOT ready")
    return 1 if problems else 0


def cmd_approve(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if cmd_check(argparse.Namespace(topics_root=args.topics_root, topic_id=args.topic_id)) != 0:
        print("refusing to approve a draft that fails check", file=sys.stderr)
        return 1
    manifest = _load(paths)
    decided_by = GateDecider(args.decided_by)
    if decided_by == GateDecider.LLM_STAND_IN:
        if not args.stand_in_model_id:
            print("LLM stand-in approval requires --stand-in-model-id", file=sys.stderr)
            return 2
        if any(seed.mandate.value == "required" for seed in manifest.question_seeds):
            print(
                "LLM stand-in cannot approve a scope carrying required question seeds",
                file=sys.stderr,
            )
            return 1
    candidate_path = _questions_path(paths)
    if candidate_path.exists():
        candidate_raw, _ = _load_question_candidates(paths)
        review_record = candidate_raw.get("review_record") or {}
        if review_record.get("decided_by") != decided_by.value:
            print(
                "scope decider must match the question-review decider; "
                "apply the review again with the correct authority",
                file=sys.stderr,
            )
            return 1
    data = manifest.model_dump(mode="json", exclude_none=False)
    data["status"] = "active"
    data["scope_approval"] = {
        "approved_by": args.approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "scope_hash": manifest.scope_hash(),
        "note": args.note,
        "decided_by": decided_by.value,
        "stand_in_model_id": args.stand_in_model_id,
    }
    approved = TopicManifest.model_validate(data)
    write_yaml(paths.topic_manifest, approved)
    print(f"approved by {args.approved_by}: {approved.scope_approval.scope_hash}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init");   p.set_defaults(func=cmd_init)
    p.add_argument("topics_root"); p.add_argument("topic_id")
    p.add_argument("--title-en", required=True)
    p.add_argument("--contributor", action="append",
                   help="name of a human answerable for this topic; repeatable")
    p.add_argument("--review-stand-in-model-id",
                   help="declare now that an LLM will stand in at touchpoint two; the "
                        "page states who reviews it and nothing may be injected after")
    p.add_argument("--group", action="append", required=True,
                   help="<group_id>:<PREFIX>, repeatable (at least two)")
    p.add_argument("--review-locale", required=True,
                   help="BCP-47 code of the language touchpoint two is read and signed "
                        "in — the language the user is holding this sitting in, not "
                        "the agent's own default; one of the site's nine")
    p.add_argument("--model-id")
    p = sub.add_parser("apply-question-review"); p.set_defaults(func=cmd_apply_question_review)
    p.add_argument("topics_root"); p.add_argument("topic_id")
    p.add_argument("--decided-by", required=True, choices=GateDecider.values())
    p.add_argument("--stand-in-model-id")
    p = sub.add_parser("check");  p.set_defaults(func=cmd_check)
    p.add_argument("topics_root"); p.add_argument("topic_id")
    p = sub.add_parser("approve"); p.set_defaults(func=cmd_approve)
    p.add_argument("topics_root"); p.add_argument("topic_id")
    p.add_argument("--approved-by", required=True)
    p.add_argument("--note")
    p.add_argument("--decided-by", required=True, choices=GateDecider.values())
    p.add_argument("--stand-in-model-id")
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
