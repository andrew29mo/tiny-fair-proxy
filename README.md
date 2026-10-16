# Tiny Fair Proxy

An experimental, single-process TCP relay with bounded application payload
buffers, backpressure and tenant-weighted byte scheduling. It forwards real TCP
streams; it is not a simulated scheduler or a production gateway.

Use it to put several trusted local clients/backends behind one explicit byte
budget and keep opening more connections from increasing a tenant's share.
Each listener maps to one tenant and one fixed backend. No application changes
or TLS termination are required.

## Run

Requires Rust 1.99.1 on macOS or Linux. For local development without a global
Rust installation, `tools/rust-env` also recognizes a project-local toolchain.

```sh
cargo build --release --locked
./target/release/tiny-fair-proxy examples/proxy.json results/local/demo
```

Start your own backend on `127.0.0.1:9001` first. The example listens on 7001 and
7002 with tenant weights 3:1. `rate_bytes_per_sec` and `burst_bytes` apply
**separately in each direction**, not as a combined full-duplex wire limit.
SIGTERM/SIGINT stops new accepts and drains live pairs up to the deadline.
State files contain listener/configuration and aggregate metrics; they do not
contain payloads or client addresses. Do not treat a stale ready file after
SIGKILL as proof that a process is alive.

## Modes and guarantees

- `connection_rr`: each eligible connection receives a byte quantum.
- `tenant_fair`: weighted deficit round robin among tenants; connection rotation
  within each tenant. Idle/non-writable tenants do not hoard service credit.
- Both modes use the same global token buckets, buffers and I/O implementation.
- Fixed payload storage is reserved at startup: `2 * buffer_bytes * max_connections`.
  Read interest pauses at capacity and resumes at half capacity.
- Bidirectional data and half-closes are independent. EOF is forwarded only after
  its buffered bytes drain. Resets/timeouts can abort queued bytes; no replay.
- Admission caps, connect/idle deadlines and a bounded drain prevent unlimited
  connection growth. Graceful shutdown is a deadline, not guaranteed delivery.

Fairness concerns bytes accepted by destination sockets under a shared shaped
bottleneck. It is not instantaneous receiver fairness, a request-latency guarantee,
identity isolation or whole-device QoS. RSS and kernel socket memory are not the
same as the payload reservation. See [architecture](docs/ARCHITECTURE.md).

## Validate and measure

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHON=.venv/bin/python ./tools/validate
.venv/bin/python tools/benchmark.py --output results/local/benchmark --blocks 3 --label native-macOS
.venv/bin/python tools/check_report.py results/local/benchmark
```

Tests start the actual release executable and real TCP peers. They exercise exact
byte order/content, simultaneous full duplex, delayed responses after half-close,
slow receivers, admission rejection, resets, idle expiry, state-directory locking,
normal draining and forced drain expiry.

Measurements use identical synthetic payloads, connection schedules, global rate,
burst and buffer settings across modes, with randomized paired order. The five
flows belong to tenant A (one connection) and B (four); weights are 1:1 and 1:3,
in upload and download. Receiver observations during a common window measure
fairness. Every trial and window-validity flag is retained. Total-work throughput
includes all tails; process RSS/CPU are sampled. JSON retains raw receiver traces,
actual issue lag, FCT, samples and final proxy accounting. HTML is derived from it.

<!-- measured:start -->
## Measured results

Native macOS ARM64 loopback; 3 randomized paired blocks, 24 trials. Each trial
completes the same five 512 KiB flows, scheduled at 0/5/10/15/20 ms, with a
512 KiB/s global cap in each direction and a 4 KiB burst. Tenant A has one
connection; B has four. Fairness uses receiver bytes during 0.4–1.4 seconds.
Every trial is retained. Ranges below are observed min–max, not confidence intervals.

| Direction | A:B weight | Mode | A share %, median [range] | Weighted Jain, median | Throughput MiB/s, median | Proxy peak RSS MiB, median |
|---|---|---|---:|---:|---:|---:|
| upload | 1:1 | connection_rr | 20.2 [20.2, 20.2] | 0.738 | 0.426 | 2.52 |
| upload | 1:1 | tenant_fair | 50.5 [50.0, 50.5] | 1.000 | 0.425 | 2.53 |
| upload | 1:3 | connection_rr | 20.0 [19.8, 20.2] | 0.980 | 0.425 | 2.52 |
| upload | 1:3 | tenant_fair | 25.7 [25.0, 25.7] | 1.000 | 0.426 | 2.53 |
| download | 1:1 | connection_rr | 20.0 [19.8, 20.2] | 0.735 | 0.426 | 2.50 |
| download | 1:1 | tenant_fair | 50.0 [49.5, 50.0] | 1.000 | 0.426 | 2.52 |
| download | 1:3 | connection_rr | 20.2 [19.8, 20.4] | 0.982 | 0.428 | 2.52 |
| download | 1:3 | tenant_fair | 25.5 [25.0, 25.7] | 1.000 | 0.427 | 2.52 |

All-flow-active windows: **24/24**. Maximum measured issue lag: **10.03 ms**.

This is a fairness trade-off under an intentionally shaped local bottleneck,
not an unshaped throughput result or a speedup over NGINX/Envoy/HAProxy.
Peak RSS is sampled for the proxy process only; kernel socket buffers and
peer processes are excluded. The fixed payload reservation is 256 KiB in
both modes. Linux/VM results are not inferred from native macOS measurements.

[Full JSON](results/native-macos-arm64/report.json) · [HTML report](results/native-macos-arm64/report.html)
<!-- measured:end -->

## Platform validation

Native macOS ARM64 and a non-root Colima Linux ARM64 container each passed
3 Rust unit tests and 18 Python test methods (including four live fairness
subcases). Three compiled production faults were detected on macOS. Linux
uses the same source manifest; its correctness run is separate from the native
performance grid. See [validation receipt and logs](reviews/mvp-20261016/README.md).

The [first hosted CI run](https://github.com/andrew29mo/tiny-fair-proxy/actions/runs/38844282524) was blocked before any steps
by GitHub account billing/spending restrictions. Neither hosted job executed;
local validation above is not a claim of hosted CI success.

## Status and license

Private MVP; no project open-source license selected. See
[third-party notices](THIRD_PARTY_NOTICES.md) and [security scope](SECURITY.md).
