"""CLI for the submission prototype (plan §6.1, §9-P2).

    python -m newsab_submission pack <topics_root> <topic_id> --out <archive.tgz> [...]
    python -m newsab_submission inspect <archive.tgz>
    python -m newsab_submission verify <archive.tgz> [--keep-work]

Exit codes: 0 = pass; 2 = structured refusal (issues printed as JSON); 1 = unexpected
error.  ``--json`` prints the machine-readable report on stdout; refusals are always
machine-readable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from newsab_schema.common import LangText
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import SponsorAttribution

from .errors import SubmissionRefused
from .g0 import ArchiveLimits, inspect_archive
from .pack import pack
from .verify import verify_archive


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, value in sorted(payload.items()):
        print(f"{key:24} {json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value}")


def cmd_pack(args: argparse.Namespace) -> int:
    sponsor = SponsorAttribution(
        anonymous=args.sponsor_name is None, display_name=args.sponsor_name
    )
    statement = LangText(text=args.statement, lang=args.statement_lang) if args.statement else None
    report = pack(
        args.topics_root,
        args.topic_id,
        args.out,
        page_run_id=args.page_run,
        operation=args.operation,
        prior_publication_id=args.prior_publication,
        requested_locales=args.locales.split(",") if args.locales else None,
        sponsor=sponsor,
        terms_version=args.terms_version,
        source_statement=statement,
        submission_id=args.submission_id,
        created_at=datetime.fromisoformat(args.created_at) if args.created_at else None,
        toolkit_ref=args.toolkit_ref,
    )
    _print(report, args.json)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    report = inspect_archive(args.archive, _limits(args))
    _print({"gate": "G0", **report.to_dict(), "ok": True}, args.json)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = verify_archive(
        args.archive,
        limits=_limits(args),
        keep_work=args.keep_work,
    )
    _print(report, args.json)
    return 0


def _limits(args: argparse.Namespace) -> ArchiveLimits:
    overrides = {
        name: getattr(args, name)
        for name in ("max_archive_bytes", "max_total_uncompressed", "max_member_bytes", "max_members")
        if getattr(args, name, None) is not None
    }
    return ArchiveLimits(**overrides)


def _add_limit_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-archive-bytes", type=int, dest="max_archive_bytes")
    parser.add_argument("--max-total-uncompressed", type=int, dest="max_total_uncompressed")
    parser.add_argument("--max-member-bytes", type=int, dest="max_member_bytes")
    parser.add_argument("--max-members", type=int, dest="max_members")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsab-submission", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="closed-list archive of one candidate page run closure")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--out", required=True, help="archive path to write (.tgz)")
    p.add_argument("--page-run", default=None, help="page run id (default: active editorial run)")
    p.add_argument(
        "--operation",
        choices=("create", "withdraw"),
        default="create",
        help="there is no revise: withdraw the publication, then create a new archive",
    )
    p.add_argument("--prior-publication", default=None, help="required for withdraw")
    p.add_argument(
        "--locales",
        default=None,
        help="comma-separated locales to publish (default: every site locale the page is "
        "written in)",
    )
    p.add_argument("--sponsor-name", default=None, help="public sponsor name (default anonymous)")
    p.add_argument("--terms-version", default="submission-terms-2")
    p.add_argument("--statement", default=None, help="source responsibility statement")
    p.add_argument("--statement-lang", default="en")
    p.add_argument("--submission-id", default=None, help="fixed id (tests/repacks)")
    p.add_argument("--created-at", default=None, help="fixed ISO timestamp (tests/repacks)")
    p.add_argument("--toolkit-ref", default=None, help="VCS ref of the toolkit used")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("inspect", help="streaming G0 archive-safety check, no extraction")
    p.add_argument("archive")
    p.add_argument("--json", action="store_true")
    _add_limit_flags(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("verify", help="G0 + G1 + G2 local verification")
    p.add_argument("archive")
    p.add_argument("--keep-work", action="store_true", help="keep the throwaway work directory")
    p.add_argument("--json", action="store_true")
    _add_limit_flags(p)
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SubmissionRefused as refusal:
        print(json.dumps(refusal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    except (ArtifactError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
