"""Topic submission archives (open_source_submission_plan §6, P2 prototype).

One topic's reviewed candidate run closure travels as a single archive.  This package
owns the contributor-facing half the plan makes public: the closed-list ``pack``
command, the streaming ``inspect`` (G0 archive safety), and the local G1 (protocol /
closure) and G2 (trusted recomputation) verification gates, all with structured,
machine-readable errors.

Nothing inside an archive is ever imported, installed, sourced or executed.  Archive
content is data; every gate either recomputes from schemas and trusted code or refuses
with a stable error code before any model or agent sees the submission.
"""

#: The submission protocol version an archive's envelope declares.  Same-major with
#: envelope minor <= verifier minor is accepted; anything else is a structured refusal,
#: never a guess (plan §6.1 version compatibility).
PROTOCOL_VERSION = "0.1.0"

#: This package's own version, recorded in envelopes it packs.
PACKAGE_VERSION = "submission-0.1.0"
