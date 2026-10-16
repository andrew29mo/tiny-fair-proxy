# Measurement protocol

The release proxy is a separate process. Python peers generate deterministic
nonperiodic SHAKE256 per-flow bytes and verify exact payloads and acknowledgements, including EOF.
No simulated network transfer, fake clock or replacement scheduler is timed.

There are five pre-established connections: A has one, B four. Payloads start at
fixed offsets 0/5/10/15/20 ms relative to a common monotonic origin. Actual issue
lag records the worker start before payload preparation, not first wire transmission.
Completion times include preparation and verification. The modes share the planned
start schedule; actual byte arrivals can differ because of scheduling and TCP
backpressure, and are not claimed to be bit-for-bit identical in time. Each flow transfers 512 KiB. Both upload and
download are exercised, with tenant weights 1:1 and 1:3. Every mode uses 512 KiB/s
per direction, a 4 KiB burst, 4 KiB quantum, 16 KiB buffers and eight reserved slots.
Only the scheduler differs. This is a shaped workload, not line-rate networking.

Schema 2 stores an explicit block count/seed and checks the complete ordered plan.
Every trial retains the actual ready configuration, compiled-source identity and
executable digest. Formal measurement rebuilds first; stale/changed executables
are rejected. Mode order is randomized with a retained seed within each paired block. Three
blocks contain 24 complete trials. No pair is discarded for weak fairness or a
slow result. A run failure prevents a final `passed` report. A run writes `running` before its first trial and records `failed` on errors,
including interrupts. Neither status passes verification; old success files are
overwritten before execution.

Fairness is observed at receivers during the same [0.4, 1.4] second window.
Each flow must have a receive observation before and after that window to label
it all-flow-active. That flag is an observable activity check, not proof of
continuous kernel writability. The report retains flags for every trial.
Weighted Jain uses tenant bytes divided by configured weight; 1 means equal
normalized service. A-share error reports deviation from the configured ratio.
Connection RR intentionally does not promise tenant fairness.

Completion times are from planned payload start to receipt of verified complete
payload/ack. Aggregate throughput divides the entire payload total by the final
completion time from the common origin, including tails, headers/ack waiting and
generator lag. It does not omit slow or unfinished flows. No request latency can
be inferred for opaque application protocols.

Proxy RSS/CPU are sampled by psutil every ~10 ms, with actual timestamps. RSS can
miss peaks and excludes peers, kernel TCP memory and VM/daemon overhead. Baseline and final snapshots bracket the full workload; CPU seconds cover that
interval, excluding startup/teardown. Baseline RSS, sampled growth, peak and maximum
sample gap are retained. A sampler error or missing coverage fails validation. Fixed
buffer reservation is reported separately from live queued bytes and RSS.
The proxy itself writes aggregate metrics every 100 ms in every mode.

Optimized Python is refused: assertion removal cannot silently weaken validation.
Peer receives have absolute deadlines even when bytes keep trickling. Unexpected
proxy exit codes and backend assertions fail the suite.

JSON includes source-file SHA-256, executable hash, raw receiver read traces,
flow receipts, all process samples and final proxy accounting. `check_report.py`
recomputes metrics, full grid, schedules, expected payload hashes, forwarded byte
counts, resource invariants and HTML. It checks the current measurement source
manifest, so measurements must be regenerated after source changes. This detects
inconsistency; it is not cryptographic attestation against a malicious producer.

These results do not establish Internet/NIC latency, link packet fairness, maximum
connection scalability, energy consumption, universal speedups or superiority over
established proxies. Loopback socket buffers affect short-window observations.
MacOS native and virtualized Linux must be labelled and reported separately.
