# Architecture and contracts

One Rust process owns a single level-triggered `poll(2)` loop and all sockets.
There is no thread-per-connection, async task queue or unbounded payload queue.
IPv4/IPv6 numeric socket addresses are accepted. Each configured listener is a
trusted tenant classification and maps to one fixed backend; it is not authentication.

## Resource ownership

At startup, `max_connections` pairs of fixed-capacity buffers are allocated and
zero-initialized. An admitted connection owns one pair until it closes. A closed
connection returns the pair. Allocation failure is a process failure, not a
successful start. Configuration caps this payload reservation at 512 MiB.
Each buffer pauses reads at capacity and resumes at half capacity; reads cannot
exceed remaining capacity. Listener/global admission caps bound connection state.
The event loop limits accepts per listener/turn and writes per turn.

The reservation covers **payload arrays only**, not process RSS, metadata, allocator
or kernel TCP buffers. `peak_queued_bytes` is a sampled event-loop high-water mark
of live payload length, not the allocated capacity. No whole-machine memory cap
or network isolation is claimed. Kernel buffers can absorb data before a blocked
receiver propagates backpressure.

## Scheduling

Upload and download each have a distinct global token bucket with the same
configured byte/s rate and burst. Tokens are debited only by successful writes.
Both modes share the exact I/O, buffer, timeout, admission and token-bucket code.

- `connection_rr`: round-robin byte quanta per eligible connection, carrying an
  unfinished visit across token exhaustion. More connections can earn more share.
- `tenant_fair`: weighted deficit round robin across tenants, and connection
  rotation inside each tenant. A tenant visit gets `quantum * weight` bytes.
  The cursor and remaining deficit survive global token exhaustion. Empty or
  non-writable tenant visits lose stored credit, preventing idle credit hoarding.

Only buffered, connected, writable destinations are eligible. The poll loop
rechecks readiness; write budgets do not cause sleeps or unbounded retries inside
one connection. Poll uses a 2 ms maximum wait, also bounding signal/timer response
under inactivity. This simple O(connections) Unix implementation prioritizes
inspectability; it is not an epoll/kqueue scalability claim.

Fairness is **bytes handed to destination sockets**, not packets on a NIC,
application requests, guaranteed minimum service or instantaneous receiver ratios.
It is meaningful under a shared shaped bottleneck with continuously demanding,
writable tenants. One idle tenant's unused bandwidth can be used by others.

## TCP and shutdown

Each direction retains read EOF separately. After that direction's buffer drains,
the peer socket's write side is shut down. Reverse traffic continues independently.
A pair completes only after both directions have delivered EOF. A reset or fatal
I/O error ends the pair; queued bytes can then be lost and are not replayed.

Connect and inactivity deadlines close affected pairs. Inactivity means no actual
successful read/write; a configured timeout can therefore close a heavily throttled
connection. SIGINT/SIGTERM closes listeners, continues existing I/O, then force-closes
remaining pairs at the drain deadline. Shutdown does not promise delivery after
resets, expiry, SIGKILL, host failure or the drain deadline. Raw TCP is not retried:
the proxy cannot know whether replaying bytes would repeat application side effects.

`ready.json` is published after binding listeners; it is removed on normal exit.
A state-directory OS file lock prevents concurrent writers. A leftover ready file
after SIGKILL is not proof of a live process. State is monitoring data, not durable
connection recovery. Metrics use same-directory temp/rename; sockets do not survive
restarts. No payloads or peer addresses are logged by default.

## Deliberate MVP exclusions

No transparent routing, HTTP parsing, TLS termination, load balancing, runtime
configuration reload, global/distributed fairness, zero-copy, untrusted plugins,
Windows support or privilege-required network configuration. Bind to loopback for
local use; listener ports classify tenants, they do not prevent impersonation.
