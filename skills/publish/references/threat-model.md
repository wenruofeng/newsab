# Publish threat model

Read this before every prepare, activate or lifecycle operation. The publish agent owns
the crossing from private/audit inputs to public output; a failure here can leak source
text or make an unreviewed page appear to carry the site's approval.

## Trust boundaries

| Boundary | Treat as | Consequence |
|---|---|---|
| Topic runs and private corpus | trusted only after schema, manifest and set restoration | Read exact pinned runs; active pointers and filenames are hints, not authority. |
| Human review/operation approval | authority bound to exact hashes and operation | Reject topic-only, stale, stand-in or ambiguous approval. |
| Submission/candidate assets | untrusted data | Never execute or directly deploy HTML, CSS, JavaScript, archives, links or symlinks. |
| `site/` artifact root | mixed visibility | Only typed publication/catalog records are public sources; events and selectors are internal; audit/submission/private trees are never deployed. `site/audit/<publication_id>/` holds only display-cleared render-input archives (bytes already shipped on the page or repo-owned config) and is versioned so a fresh clone can re-verify; anything not display-cleared goes to submissions/ or private/, which never enter the repository. |
| Final public directory | hostile-review surface | Assemble from a closed list, scan the finished bytes and deploy only the fingerprinted directory. |

## Threats and required controls

| Threat | Control and refusal |
|---|---|
| Review/build time-of-check gap | Re-render into fresh scratch from the pinned closure, then compare the final reviewer-locale hash. Any byte change requires a new review. |
| Mutable active-pointer drift | Resolve every dependency from qualified publication pins. Never read `manifest/active.json` after resolution and never use it as a production selector. |
| Full-text or private-data leak | Copy no source tree. Emit a closed list, apply both topic/site visibility classifiers, enforce the per-article sentence budget, scan output for private paths and known forbidden records. Any hit blocks the entire release. |
| Candidate code execution or path escape | Parse candidates as typed data. Reject absolute/parent paths, links, symlinks, undeclared files and executable content; generate site HTML/CSS/JS only from repository-owned code. |
| Unsupported or altered claim | Re-run page/finding/count/quote checks from pinned inputs. Publish cannot waive, relabel or rewrite a finding. |
| Catalog as second truth | Derive localized questions, answers, groups, scope and fragments from the pinned page/publication plus versioned site metadata. Reject supplied duplicates even if they look identical. |
| Nondeterministic or partial deploy | Build twice in empty roots and compare fingerprints. Write immutable record first, fsync one event, derive all caches, then atomically switch the complete release. A failed switch leaves the old release live. |
| Event replay, fork or illegal transition | Lock the append-only stream, verify its prior hash and every publication byte hash, reject duplicate ids and derive state through the schema state machine. Never edit selector/catalog to override it. |
| Attribution or credential leak | Public sponsor data contains only display choice; worker credit is model id + backed run ids. Submission control tokens, private contacts and operator credentials never enter publication or catalog. |
| Withdrawal mistaken for deletion | Withdrawal is an event and removes the live selector entry. Physical audit deletion is a separately approved exception; retain a content-free event and never erase unrelated history. The immutable `publication.json` itself must stay on disk even after `audit_delete` — every later event append re-verifies the whole chain's hash bindings, so deleting a record file permanently blocks all further lifecycle events. |

## Failure posture

All controls fail closed before production mutation. Diagnostics may name an artifact path,
schema field, hash and failed invariant; they must not echo corpus sentences, credentials or
private contact data. Retrying is safe only after rebuilding from a fresh scratch directory
and re-reading the current event head. Repeated failure never grants permission to weaken a
check or deploy a preview.

