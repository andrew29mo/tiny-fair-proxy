# MVP evidence — 2026-10-16

Historical record: the later [MIT adoption](../mit-adoption-20261016/README.md)
supersedes the unselected-license status recorded here.

The native macOS ARM64 run uses the actual release binary and real loopback TCP
peers. Three Rust unit tests and 18 Python test methods passed, including four
live weighted-fairness subcases, exact byte/EOF checks, slow consumers, independently
exercised tenant/global admission limits, rate budget, reset, idle expiry, normal
and forced draining, state locking and report tampering checks.

Three deliberate faults were compiled into the production source in separate
local builds. The behavioral suites failed as required for premature half-close,
ignored tenant weights and omitted token charging. Logs retain those **expected
failures**; they are not failed tests of the submitted release binary. Absolute
repository paths in published test logs are replaced with `<repo>` and trailing
whitespace is removed. Ignored original logs remain local.

The final measurement grid has three randomized paired blocks, 24 trials, both
directions and weights 1:1 / 1:3, using identical pre-established flow schedules,
bytes, rate/burst and buffer reservations. All five flows were observed active
across every fairness window. JSON retains every receiver observation and process
sample; HTML/README are checked against it. Environment and source hashes are in
[receipt.json](receipt.json). No external proxy benchmark or line-rate claim is made.

Development counterexamples and earlier runs remain ignored locally. In particular,
one interrupted run exposed inefficient tiny writes at fractional token refill;
credit batching was added. A subsequent live 1:3 test caught loss of remaining DRR
credit while waiting for a batch. Both were fixed before the retained final run.
No speedup is inferred by comparing those exploratory runs with the final grid.

A non-root Linux ARM64 container inside Colima passed the same 18 Python methods
and four fairness subcases; the image build also passed all three Rust unit tests.
The container used a read-only root, loopback-only network, two CPUs and a 512 MiB
limit. Actual exit code was 0 with no OOM, and the owned container was removed.
Linux Python is Debian 3.11.2; native Python is 3.12. These are separate correctness
observations with matching source manifests, not identical runtime environments.
The hosted run for commit `14884d6` was blocked before either job started by
GitHub account billing/spending restrictions. Its annotation and URL are in the
receipt; no hosted test success is claimed. Native measurements are not virtual-machine
memory or Linux performance observations.
Project licensing remains unselected; third-party licenses are listed separately.

## Historical scope after scheduling review

This receipt and its logs describe the original MVP at `11d0923`; they are not
relabelled as validation of the reviewed implementation. The original measurement
JSON/HTML are preserved byte-for-byte under
[`results/historical-mvp-11d0923`](../../results/historical-mvp-11d0923/).
The [scheduling review](../scheduling-review-20261016/README.md) documents a staging-
buffer fairness bug and validator gaps, fixes and new schema-2 observations.
Use the root README for current results and limitations.
