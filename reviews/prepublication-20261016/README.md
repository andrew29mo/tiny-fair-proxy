# Pre-publication review — 2026-10-16

Historical record of commit `7fe3609`. The later
[MIT adoption](../mit-adoption-20261016/README.md) supersedes the unselected-license
status below; this receipt and its observations are retained unchanged.
The unchanged report pair is in
[`results/historical-prepublication-7fe3609`](../../results/historical-prepublication-7fe3609/).

Baseline: `8617ad0e42de355079aeb6c6cb658c16c1a8d312`, initially clean.
The repository remains Private with no added collaborators. No project license
has been selected or granted by this review. A public/open-source release still
needs the owner's license decision; dependency notices are not a project license.

## Finding and correction

The retained performance data matched the source, but a failed new measurement
could leave **old successful HTML** in its output directory. A build failure
could leave **both old JSON and HTML** marked successful. The counterexample in
`counterexamples.json` reproduces this against the baseline harness.

The benchmark now invalidates both artifacts before compilation and catches
compilation failures as failed JSON. A trial failure or a partial HTML-write
failure also leaves failed JSON with no success HTML. The existing artifact
regression method covers all three stages. Its injected trial/render fixtures
test artifact control only; they are not measurement or relay correctness data.
TCP correctness tests continue to execute the actual release binary and peers.

Rust runtime code is unchanged from the scheduling review. The final 24-trial
measurement was regenerated because the Python benchmark/test manifest changed.
Earlier reports and their unchanged receipts are explicitly historical, including
the [original MVP](../../results/historical-mvp-11d0923/) and
[scheduling review](../../results/historical-review-8617ad0/).

## Verification and claims

`receipt.json` binds the reviewed source, native executable, report, platform
observations and adjacent sanitized test logs. Native macOS and non-root Linux
ARM64 container reruns each check four Rust units and 33 Python test methods.
Linux uses the same source manifest; it is a VM/container correctness check,
not native Linux performance evidence. The owned container is removed and Colima
is stopped after validation. Earlier four mutation detections remain historical
behavioral evidence for the unchanged Rust source, not a new mutation run.

All 24 native trials, tails, receiver observations, RSS/CPU samples and outcome/
byte ledgers are retained. README values and HTML are recomputed from the JSON.
The workload has five pre-established flows, planned worker starts, a shaped
512 KiB/s bottleneck per direction, and three paired blocks. Actual wire arrivals
can differ. Fairness values are rounded and do not guarantee continuous readiness,
exact ratios or an SLA. RSS is sampled proxy-process RSS and excludes peers,
kernel buffers and VM overhead. No universal speedup, memory saving, line-rate
scalability or superiority over another proxy is claimed.

## File and license checks

Reachable Git history and current tracked files were checked for private paths,
credential signatures/URLs, unexpected binaries, large files and personal/local
configuration paths. Git author/committer addresses use the owner's GitHub noreply
identity. Toolchains, environments, raw local logs and personal instructions stay
ignored. Published logs replace personal path prefixes and strip trailing spaces;
their original and published hashes are recorded separately. This is a heuristic
review, not proof that no secret can exist.

Locked dependency names, versions and declared licenses match Cargo metadata and
`docs/DEPENDENCIES.md`; dependencies are not vendored. `Cargo.toml` has
`publish = false` and no project license identifier; no root LICENSE is present.
README, third-party notices and GitHub's null license recognition agree.

The workflow uses SHA-pinned actions, read-only contents permissions, no persisted
checkout credentials and no pull-request write/approval step. Hosted CI billing
restrictions are reported separately from local passes; no hosted success is
inferred. Private visibility is checked again after upload.
