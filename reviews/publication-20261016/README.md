# Public release — 2026-10-16

Reviewed baseline: `e8f9852156268dd4b18ee60cb9119524c06184cb`. The owner explicitly
authorized publication after independent agent review. Two read-only passes
covered implementation/test/report evidence and license/history/workflow hygiene;
neither found a confirmed release blocker. Their scope was experimental trusted
local TCP forwarding, not certification for an Internet-facing production proxy.

The repository is Public under MIT. README and third-party notice wording are
updated; earlier Private observations and receipt hashes remain historical.
No implementation, test, dependency lockfile or measurement-tool changes are made
for publication, so the retained source-bound 24-trial measurement remains valid.

## Platform and measurement evidence

The MIT-adoption receipt, current source manifest, native executable, JSON/HTML,
license inventory and platform logs were checked by SHA-256. The native suite
was rerun for publication: four Rust tests and 33 Python test methods passed.
Linux evidence is the retained same-source non-root ARM64 container run from MIT
adoption (four Rust tests and 33 Python test methods); no new Linux rerun or VM
performance is claimed by this release. Its recorded exit was 0, without OOM,
with container removal and stopped VM. See `receipt.json` and the linked
[MIT adoption evidence](../mit-adoption-20261016/README.md).

All 24 trials, the canonical HTML and generated README measurements pass
verification. Results remain native macOS loopback under the stated shaped
workload; RSS excludes kernel buffers and peer/VM processes. Historical reports
are not additional replications. The review does not establish universal speedup,
hard latency/fairness guarantees or absence of undiscovered defects.

## Publication hygiene and repository controls

The independent history scan covered all five baseline commits and 114 reachable
blobs, plus 80 tracked files, with no flagged private paths, credential patterns,
personal instructions or binary artifacts. Scanning is heuristic. All 29 selected
third-party license texts match their installed locked sources; Unicode-3.0 and
psutil BSD terms remain separate from the project's MIT license.

Public settings are read back after enabling secret scanning, push protection,
Dependabot alerts/security
updates and all-external-contributor fork-PR approval. Actions retain read-only
default tokens, no PR approval permission, only checkout/setup-python allowed and
mandatory SHA pinning. Main history cannot be deleted or force-pushed through a
configured bypass. Required Linux/macOS checks have a repository-admin bypass
for the sole maintainer. No approval from a second maintainer is required, and no
collaborator, deploy key, webhook or self-hosted runner is added.

These settings are defense in depth, not a guarantee against a compromised
administrator or unrecognized secrets/dependency vulnerabilities. Alert counts
are point-in-time observations; a zero count is not proof a scan is exhaustive.
Optional non-provider-pattern and validity-check settings read back disabled
after API enable requests; no coverage from these optional settings is claimed.
Private-era CI failures were account-billing blocks with zero executed steps;
post-publication hosted execution is reported separately from local evidence.
