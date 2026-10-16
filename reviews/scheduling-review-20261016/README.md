# Scheduling and evidence review — 2026-10-16

This record describes commit `8617ad0` and is historical after the
[pre-publication review](../prepublication-20261016/README.md). Its unchanged
schema-2 JSON/HTML are now in
[`results/historical-review-8617ad0`](../../results/historical-review-8617ad0/).
The root README and `results/native-macos-arm64` describe the latest version.

Reviewed baseline: `11d0923456a7752dc622c4934ef93da64b417105`.
The baseline worktree was clean. No owner edits were overwritten. Repository
visibility stays Private; project licensing stays unselected.

## Reproduced findings and fixes

1. **Staging capacity truncated weighted service.** With two backlogged TCP flows,
   weights 1:3, 1 KiB buffers and 4 KiB quantum, the original receiver window showed
   52,799 / 79,332 bytes (39.96% / 60.04%) rather than 25% / 75%. Both flows were
   active before and after the window. The scheduler treated an empty application
   staging buffer as an idle source and retired its remaining credit. It now
   attempts a bounded nonblocking refill before retiring a visit. The same probe
   after the fix showed 32,768 / 98,382 bytes (24.99% / 75.01%). Dedicated actual-
   executable tests cover both directions and the four original fairness cases.
   These probe figures are not performance speedups.
2. **Incomplete reports could pass.** Removing two entire blocks left eight trials
   that the original verifier accepted; it inferred the plan from remaining rows.
   Empty share/target vectors also passed truncated zip comparisons. Schema 2
   records the planned block count/seed, verifies exact ordered identities and
   vector lengths, and compares actual runtime configuration and binary identity.
3. **Optimized Python removed checks.** The original `python -O` verifier accepted
   a report explicitly marked failed. Validation now refuses optimized Python.
   Regressions also check partial/failed runs cannot leave an old successful JSON,
   and sampler failures/missing interval coverage cannot silently pass.
4. **Execution binding and harness gaps.** Formal measurement previously hashed
   source and binary independently without proving they corresponded. Release now
   embeds build-time Rust/Cargo/build-script digests; tests reject stale binaries,
   and formal measurement rebuilds and checks executable stability per trial.
   Unexpected proxy exit codes fail teardown. Receives have absolute deadlines
   even with dribbling peers. Backend assertions and thread cleanup are checked.
5. **Aborted data lacked a ledger.** Received, forwarded, discarded and queued
   bytes now balance in both directions, globally and per tenant. Admission counts
   include synchronous backend-connect failures; each admitted pair has a terminal
   or live disposition. New tests check forced drain, queued-tail drain, reverse
   half-close, slow upload/download recovery and reuse with nonperiodic payloads.

`counterexamples.json` records the original probes. Original performance JSON/HTML
remain unchanged in `results/historical-mvp-11d0923`; current schema-2 results are
regenerated from the reviewed code. The original tests passing is not evidence
that their omitted boundary cases were correct.

## Verification scope

Final commands, counts, source/executable hashes and environment observations are
in `receipt.json` and the adjacent sanitized logs. Native macOS full measurements
run with Colima stopped and without concurrent heavy tests. Linux inside Colima
is a separate correctness observation, not native or whole-VM performance evidence.
Deliberate production faults are tested in separate builds; source-identity checking
is explicitly bypassed there so only behavior assertions count as detections.

Connection timeout expiry also has a deterministic unit test of the production
supervisor with real TCP sockets and an aged start instant. It is not a claim
of packet-loss/blackhole testing on a physical network.

## Remaining limits

Receiver-window activity is an observable check, not proof of continuous kernel
writability. Fairness is byte service under the stated shaped bottleneck, not a
wire QoS/SLA, arbitrary traffic guarantee or third-party performance comparison.
RSS is sampled process RSS and may miss peaks; kernel buffers, peers and VM overhead
are excluded. The new report retains baseline, growth and maximum sample gap.
The byte ledger covers bytes actually read by the proxy; it cannot account for
unread client/kernel bytes or prove application side effects. Explicit rejection
counts exclude connections that never reach accept (such as kernel backlog loss).
Source identities and file hashes are consistency checks, not execution attestation
against a malicious producer. Secret/path scanning is heuristic.
