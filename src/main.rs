//! One level-triggered poll loop owns every socket and every byte budget.
use serde::{Deserialize, Serialize};
use socket2::{Domain, Protocol, Socket, Type};
use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Tenant {
    name: String,
    listen: SocketAddr,
    backend: SocketAddr,
    weight: usize,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Config {
    mode: String,
    rate_bytes_per_sec: usize,
    burst_bytes: usize,
    quantum_bytes: usize,
    buffer_bytes: usize,
    max_connections: usize,
    max_connections_per_tenant: usize,
    connect_timeout_ms: u64,
    idle_timeout_ms: u64,
    drain_timeout_ms: u64,
    tenants: Vec<Tenant>,
}
impl Config {
    fn validate(&self) -> Result<(), String> {
        if !["connection_rr", "tenant_fair"].contains(&self.mode.as_str()) {
            return Err("mode must be connection_rr or tenant_fair".into());
        }
        if self.tenants.is_empty()
            || self.tenants.len() > 64
            || self.rate_bytes_per_sec == 0
            || self.rate_bytes_per_sec > 1_000_000_000
            || self.burst_bytes == 0
            || self.burst_bytes > 16 * 1024 * 1024
            || self.quantum_bytes == 0
            || self.quantum_bytes > 1024 * 1024
            || !(1024..=1024 * 1024).contains(&self.buffer_bytes)
            || !(1..=4096).contains(&self.max_connections)
            || self.max_connections_per_tenant == 0
            || self.max_connections_per_tenant > self.max_connections
            || self.connect_timeout_ms == 0
            || self.idle_timeout_ms == 0
            || self.drain_timeout_ms == 0
            || self.connect_timeout_ms > 3_600_000
            || self.idle_timeout_ms > 86_400_000
            || self.drain_timeout_ms > 3_600_000
        {
            return Err("invalid resource/time bound".into());
        }
        if self
            .max_connections
            .checked_mul(2 * self.buffer_bytes)
            .filter(|n| *n <= 512 * 1024 * 1024)
            .is_none()
        {
            return Err("reserved payload memory exceeds 512 MiB".into());
        }
        let mut names = std::collections::BTreeSet::new();
        for t in &self.tenants {
            if t.name.is_empty()
                || t.name.len() > 64
                || !t
                    .name
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
                || !names.insert(&t.name)
                || t.weight == 0
                || t.weight > 64
                || t.backend.port() == 0
            {
                return Err("invalid tenant name, weight or backend".into());
            }
        }
        Ok(())
    }
}

struct Buffer {
    data: Vec<u8>,
    start: usize,
    end: usize,
    paused: bool,
}
impl Buffer {
    fn new(size: usize) -> Self {
        Self {
            data: vec![0; size],
            start: 0,
            end: 0,
            paused: false,
        }
    }
    fn len(&self) -> usize {
        self.end - self.start
    }
    fn consume(&mut self, n: usize) {
        self.start += n;
        if self.start == self.end {
            self.start = 0;
            self.end = 0;
        }
        if self.len() <= self.data.len() / 2 {
            self.paused = false;
        }
    }
    fn prepare(&mut self) {
        if self.end == self.data.len() && self.start > 0 {
            self.data.copy_within(self.start..self.end, 0);
            self.end -= self.start;
            self.start = 0;
        }
    }
}
struct Bucket {
    tokens: f64,
    rate: f64,
    burst: f64,
    updated: Instant,
}
impl Bucket {
    fn new(rate: usize, burst: usize) -> Self {
        Self {
            tokens: burst as f64,
            rate: rate as f64,
            burst: burst as f64,
            updated: Instant::now(),
        }
    }
    fn refill(&mut self, now: Instant) {
        self.tokens = (self.tokens + now.duration_since(self.updated).as_secs_f64() * self.rate)
            .min(self.burst);
        self.updated = now;
    }
    fn available(&self) -> usize {
        self.tokens.floor() as usize
    }
    fn write_ready(&self, quantum: usize) -> bool {
        // Batch at most ~10 ms of credit. Avoid continuously-ready sockets
        // turning fractional refills into a stream of one-byte writes.
        let batch = quantum
            .min(self.burst as usize)
            .min((self.rate as usize / 100).max(1));
        self.available() >= batch
    }
    fn charge(&mut self, n: usize) {
        self.tokens -= n as f64;
    }
}
struct Conn {
    tenant: usize,
    sockets: [TcpStream; 2],
    buffers: [Buffer; 2],
    eof: [bool; 2],
    fin_sent: [bool; 2],
    connecting: bool,
    created: Instant,
    last_io: Instant,
    writable: [bool; 2],
}
#[derive(Serialize, Default)]
struct TenantStats {
    accepted: u64,
    rejected: u64,
    forwarded: [u64; 2],
    pauses: u64,
    peak_queued_bytes: usize,
}
#[derive(Serialize, Default)]
struct Metrics {
    accepted: u64,
    rejected: u64,
    completed: u64,
    io_errors: u64,
    connect_errors: u64,
    connect_timeouts: u64,
    idle_timeouts: u64,
    forced_drain: u64,
    paused_reads: u64,
    current_connections: usize,
    peak_connections: usize,
    peak_queued_bytes: usize,
    reserved_payload_bytes: usize,
    tenants: Vec<TenantStats>,
    elapsed_seconds: f64,
}
/// Persistent DRR cursor/deficit: token exhaustion does NOT rotate a partially served visit.
struct Drr {
    cursor: usize,
    deficit: Vec<usize>,
    conn_cursor: Vec<u64>,
}
impl Drr {
    fn new(n: usize) -> Self {
        Self {
            cursor: 0,
            deficit: vec![0; n],
            conn_cursor: vec![0; n],
        }
    }
}
struct Proxy {
    cfg: Config,
    listeners: Vec<TcpListener>,
    conns: BTreeMap<u64, Conn>,
    next: u64,
    metrics: Metrics,
    pool: Vec<[Buffer; 2]>,
    buckets: [Bucket; 2],
    sched: [Drr; 2],
    rr: [u64; 2],
    rr_left: [usize; 2],
    started: Instant,
}
fn connecting(addr: SocketAddr) -> io::Result<TcpStream> {
    let socket = Socket::new(Domain::for_address(addr), Type::STREAM, Some(Protocol::TCP))?;
    socket.set_nonblocking(true)?;
    match socket.connect(&addr.into()) {
        Ok(()) => {}
        Err(e)
            if e.kind() == io::ErrorKind::WouldBlock
                || e.raw_os_error() == Some(libc::EINPROGRESS) => {}
        Err(e) => return Err(e),
    }
    let s: TcpStream = socket.into();
    s.set_nodelay(true)?;
    Ok(s)
}
fn atomic_json(path: &Path, value: &impl Serialize) -> io::Result<()> {
    let temp = path.with_extension("tmp");
    fs::write(&temp, serde_json::to_vec_pretty(value)?)?;
    fs::rename(temp, path)
}
impl Proxy {
    fn new(cfg: Config) -> io::Result<Self> {
        cfg.validate().map_err(io::Error::other)?;
        let mut listeners = Vec::new();
        for t in &cfg.tenants {
            let l = TcpListener::bind(t.listen)?;
            l.set_nonblocking(true)?;
            listeners.push(l);
        }
        let mut pool = Vec::new();
        for _ in 0..cfg.max_connections {
            pool.push([Buffer::new(cfg.buffer_bytes), Buffer::new(cfg.buffer_bytes)]);
        }
        let metrics = Metrics {
            reserved_payload_bytes: cfg.max_connections * 2 * cfg.buffer_bytes,
            tenants: (0..cfg.tenants.len())
                .map(|_| TenantStats::default())
                .collect(),
            ..Default::default()
        };
        Ok(Self {
            buckets: [
                Bucket::new(cfg.rate_bytes_per_sec, cfg.burst_bytes),
                Bucket::new(cfg.rate_bytes_per_sec, cfg.burst_bytes),
            ],
            sched: [Drr::new(cfg.tenants.len()), Drr::new(cfg.tenants.len())],
            rr: [0; 2],
            rr_left: [0; 2],
            listeners,
            conns: BTreeMap::new(),
            next: 1,
            metrics,
            pool,
            started: Instant::now(),
            cfg,
        })
    }
    fn accept(&mut self, t: usize) -> io::Result<()> {
        // Bound each listener's work per turn to keep an accept flood from starving data.
        for _ in 0..32 {
            match self.listeners[t].accept() {
                Ok((client, _)) => {
                    let count = self.conns.values().filter(|c| c.tenant == t).count();
                    if self.conns.len() >= self.cfg.max_connections
                        || count >= self.cfg.max_connections_per_tenant
                    {
                        self.metrics.rejected += 1;
                        self.metrics.tenants[t].rejected += 1;
                        drop(client);
                        continue;
                    }
                    client.set_nonblocking(true)?;
                    client.set_nodelay(true)?;
                    match connecting(self.cfg.tenants[t].backend) {
                        Ok(backend) => {
                            let mut buffers = self.pool.pop().expect("reserved slot");
                            for b in &mut buffers {
                                b.start = 0;
                                b.end = 0;
                                b.paused = false;
                            }
                            let now = Instant::now();
                            self.conns.insert(
                                self.next,
                                Conn {
                                    tenant: t,
                                    sockets: [client, backend],
                                    buffers,
                                    eof: [false; 2],
                                    fin_sent: [false; 2],
                                    connecting: true,
                                    created: now,
                                    last_io: now,
                                    writable: [false; 2],
                                },
                            );
                            self.next += 1;
                            self.metrics.accepted += 1;
                            self.metrics.tenants[t].accepted += 1;
                            self.metrics.peak_connections =
                                self.metrics.peak_connections.max(self.conns.len());
                        }
                        Err(_) => self.metrics.connect_errors += 1,
                    }
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }
    fn remove(&mut self, id: u64) {
        if let Some(c) = self.conns.remove(&id) {
            self.pool.push(c.buffers);
        }
    }
    fn read_conn(&mut self, id: u64, e: usize) -> io::Result<()> {
        let c = self.conns.get_mut(&id).unwrap();
        if c.eof[e] || c.buffers[e].paused || (e == 1 && c.connecting) {
            return Ok(());
        }
        let b = &mut c.buffers[e];
        b.prepare();
        loop {
            if b.end == b.data.len() {
                if !b.paused {
                    self.metrics.paused_reads += 1;
                    self.metrics.tenants[c.tenant].pauses += 1;
                }
                b.paused = true;
                break;
            }
            match c.sockets[e].read(&mut b.data[b.end..]) {
                Ok(0) => {
                    c.eof[e] = true;
                    break;
                }
                Ok(n) => {
                    b.end += n;
                    c.last_io = Instant::now();
                }
                Err(err) if err.kind() == io::ErrorKind::WouldBlock => break,
                Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
                Err(err) => return Err(err),
            }
        }
        Ok(())
    }
    fn write_conn(&mut self, id: u64, d: usize, limit: usize) -> io::Result<usize> {
        let c = self.conns.get_mut(&id).unwrap();
        let dst = 1 - d;
        let b = &mut c.buffers[d];
        let n = limit.min(b.len()).min(self.buckets[d].available());
        if n == 0 || !c.writable[dst] || c.connecting {
            return Ok(0);
        }
        match c.sockets[dst].write(&b.data[b.start..b.start + n]) {
            Ok(0) => Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "socket write zero",
            )),
            Ok(written) => {
                b.consume(written);
                c.last_io = Instant::now();
                self.buckets[d].charge(written);
                self.metrics.tenants[c.tenant].forwarded[d] += written as u64;
                Ok(written)
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                c.writable[dst] = false;
                Ok(0)
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => Ok(0),
            Err(e) => Err(e),
        }
    }
    fn eligible(&self, id: u64, d: usize) -> bool {
        let c = &self.conns[&id];
        !c.connecting && c.writable[1 - d] && c.buffers[d].len() > 0
    }
    fn schedule(&mut self, d: usize) {
        // No writable interest was requested while waiting for a credit batch.
        // Preserve the current DRR visit rather than treating that as peer blockage.
        if !self.buckets[d].write_ready(self.cfg.quantum_bytes) {
            return;
        }
        // CPU budget bounds one turn even with tiny writes or continuously-ready peers.
        for _ in 0..4096 {
            if self.buckets[d].available() == 0 {
                break;
            }
            let candidate = if self.cfg.mode == "tenant_fair" {
                let n = self.cfg.tenants.len();
                let mut found = None;
                for _ in 0..n {
                    let t = self.sched[d].cursor;
                    let ids: Vec<u64> = self
                        .conns
                        .iter()
                        .filter(|(id, c)| c.tenant == t && self.eligible(**id, d))
                        .map(|(id, _)| *id)
                        .collect();
                    if ids.is_empty() {
                        self.sched[d].deficit[t] = 0;
                        self.sched[d].cursor = (t + 1) % n;
                        continue;
                    }
                    if self.sched[d].deficit[t] == 0 {
                        self.sched[d].deficit[t] =
                            self.cfg.quantum_bytes * self.cfg.tenants[t].weight;
                    }
                    let previous = self.sched[d].conn_cursor[t];
                    let id = *ids.iter().find(|id| **id > previous).unwrap_or(&ids[0]);
                    found = Some((id, self.sched[d].deficit[t], Some(t)));
                    break;
                }
                found
            } else {
                let ids: Vec<u64> = self
                    .conns
                    .keys()
                    .copied()
                    .filter(|id| self.eligible(*id, d))
                    .collect();
                if ids.is_empty() {
                    None
                } else {
                    let id = if self.rr_left[d] > 0 && ids.contains(&self.rr[d]) {
                        self.rr[d]
                    } else {
                        self.rr_left[d] = self.cfg.quantum_bytes;
                        *ids.iter().find(|id| **id > self.rr[d]).unwrap_or(&ids[0])
                    };
                    self.rr[d] = id;
                    Some((id, self.rr_left[d], None))
                }
            };
            let Some((id, limit, tenant)) = candidate else {
                break;
            };
            match self.write_conn(id, d, limit) {
                Ok(n) => {
                    if let Some(t) = tenant {
                        self.sched[d].deficit[t] -= n;
                        self.sched[d].conn_cursor[t] = id;
                        if self.sched[d].deficit[t] == 0 {
                            self.sched[d].cursor = (t + 1) % self.cfg.tenants.len();
                        }
                    } else {
                        self.rr_left[d] -= n;
                        if n == 0 {
                            self.rr_left[d] = 0;
                        }
                    }
                    if n == 0 {
                        break;
                    }
                }
                Err(_) => {
                    self.metrics.io_errors += 1;
                    self.remove(id);
                }
            }
        }
    }
    fn finish_and_expire(&mut self) {
        let now = Instant::now();
        let mut remove = Vec::new();
        for (id, c) in &mut self.conns {
            if c.connecting
                && now.duration_since(c.created)
                    >= Duration::from_millis(self.cfg.connect_timeout_ms)
            {
                self.metrics.connect_timeouts += 1;
                remove.push(*id);
                continue;
            }
            if now.duration_since(c.last_io) >= Duration::from_millis(self.cfg.idle_timeout_ms) {
                self.metrics.idle_timeouts += 1;
                remove.push(*id);
                continue;
            }
            if !c.connecting {
                for d in 0..2 {
                    if c.eof[d] && c.buffers[d].len() == 0 && !c.fin_sent[d] {
                        if c.sockets[1 - d].shutdown(Shutdown::Write).is_err() {
                            self.metrics.io_errors += 1;
                            remove.push(*id);
                            break;
                        }
                        c.fin_sent[d] = true;
                    }
                }
            }
            if c.fin_sent == [true, true] {
                self.metrics.completed += 1;
                remove.push(*id);
            }
        }
        remove.sort_unstable();
        remove.dedup();
        for id in remove {
            self.remove(id);
        }
    }
    fn update_metrics(&mut self) {
        let mut totals = vec![0; self.cfg.tenants.len()];
        for c in self.conns.values() {
            totals[c.tenant] += c.buffers.iter().map(Buffer::len).sum::<usize>();
        }
        self.metrics.peak_queued_bytes = self.metrics.peak_queued_bytes.max(totals.iter().sum());
        for (t, n) in totals.iter().enumerate() {
            self.metrics.tenants[t].peak_queued_bytes =
                self.metrics.tenants[t].peak_queued_bytes.max(*n);
        }
        self.metrics.current_connections = self.conns.len();
        self.metrics.elapsed_seconds = self.started.elapsed().as_secs_f64();
    }
    fn run(&mut self, stop: Arc<AtomicBool>, metrics_path: &Path) -> io::Result<()> {
        let mut drain = None;
        let mut last_report = Instant::now();
        loop {
            if stop.load(Ordering::Relaxed) && drain.is_none() {
                drain = Some(Instant::now());
                self.listeners.clear();
            }
            if let Some(start) = drain {
                if self.conns.is_empty() {
                    break;
                }
                if start.elapsed() >= Duration::from_millis(self.cfg.drain_timeout_ms) {
                    self.metrics.forced_drain += self.conns.len() as u64;
                    let ids: Vec<_> = self.conns.keys().copied().collect();
                    for id in ids {
                        self.remove(id);
                    }
                    break;
                }
            }
            for b in &mut self.buckets {
                b.refill(Instant::now());
            }
            let mut fds = Vec::new();
            let mut refs = Vec::new();
            for (t, l) in self.listeners.iter().enumerate() {
                fds.push(libc::pollfd {
                    fd: l.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                });
                refs.push((0, t));
            }
            for (id, c) in &mut self.conns {
                c.writable = [false; 2];
                for e in 0..2 {
                    let mut events = 0;
                    if !c.eof[e] && !c.buffers[e].paused && !(e == 1 && c.connecting) {
                        events |= libc::POLLIN;
                    }
                    if (e == 1 && c.connecting)
                        || (!c.connecting
                            && c.buffers[1 - e].len() > 0
                            && self.buckets[1 - e].write_ready(self.cfg.quantum_bytes))
                    {
                        events |= libc::POLLOUT;
                    }
                    if events != 0 {
                        fds.push(libc::pollfd {
                            fd: c.sockets[e].as_raw_fd(),
                            events,
                            revents: 0,
                        });
                        refs.push((*id, e));
                    }
                }
            }
            // Poll is level-triggered. Bounded reads need not drain to EAGAIN.
            // SAFETY: vector owns valid pollfd storage; descriptors stay live for the call.
            let ret = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, 2) };
            if ret < 0 {
                let e = io::Error::last_os_error();
                if e.kind() != io::ErrorKind::Interrupted {
                    return Err(e);
                }
            }
            for (fd, (id, e)) in fds.iter().zip(refs) {
                if fd.revents == 0 {
                    continue;
                }
                if id == 0 {
                    if drain.is_none() {
                        self.accept(e)?;
                    }
                    continue;
                }
                if !self.conns.contains_key(&id) {
                    continue;
                }
                if e == 1
                    && self.conns[&id].connecting
                    && fd.revents & (libc::POLLOUT | libc::POLLERR | libc::POLLHUP) != 0
                {
                    let c = self.conns.get_mut(&id).unwrap();
                    if c.sockets[1].take_error()?.is_some() || c.sockets[1].peer_addr().is_err() {
                        self.metrics.connect_errors += 1;
                        self.remove(id);
                        continue;
                    }
                    c.connecting = false;
                }
                if fd.revents & libc::POLLNVAL != 0 {
                    self.metrics.io_errors += 1;
                    self.remove(id);
                    continue;
                }
                if fd.revents & libc::POLLOUT != 0 {
                    self.conns.get_mut(&id).unwrap().writable[e] = true;
                }
                if fd.revents & (libc::POLLIN | libc::POLLHUP | libc::POLLERR) != 0
                    && self.read_conn(id, e).is_err()
                {
                    self.metrics.io_errors += 1;
                    self.remove(id);
                }
            }
            self.update_metrics();
            for d in 0..2 {
                self.schedule(d);
            }
            self.finish_and_expire();
            self.update_metrics();
            if last_report.elapsed() >= Duration::from_millis(100) {
                atomic_json(metrics_path, &self.metrics)?;
                last_report = Instant::now();
            }
        }
        self.update_metrics();
        atomic_json(metrics_path, &self.metrics)
    }
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: tiny-fair-proxy CONFIG.json STATE_DIRECTORY".into());
    }
    let cfg: Config = serde_json::from_slice(&fs::read(&args[1])?)?;
    cfg.validate().map_err(io::Error::other)?;
    let state = PathBuf::from(&args[2]);
    fs::create_dir_all(&state)?;
    // One process per state directory; flock is released by the OS even on SIGKILL.
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(state.join("process.lock"))?;
    // SAFETY: valid owned file descriptor; no memory pointers are passed.
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("state directory already in use".into());
    }
    // Remove previous readiness before any operation which can fail.
    let _ = fs::remove_file(state.join("ready.json"));
    let mut p = Proxy::new(cfg.clone())?;
    let stop = Arc::new(AtomicBool::new(false));
    signal_hook::flag::register(signal_hook::consts::SIGTERM, Arc::clone(&stop))?;
    signal_hook::flag::register(signal_hook::consts::SIGINT, Arc::clone(&stop))?;
    let listeners: Vec<_> = p
        .listeners
        .iter()
        .map(|l| l.local_addr().unwrap().to_string())
        .collect();
    atomic_json(&state.join("metrics.json"), &p.metrics)?;
    atomic_json(
        &state.join("ready.json"),
        &serde_json::json!({"listeners":listeners,"config":cfg}),
    )?;
    let result = p.run(stop, &state.join("metrics.json"));
    let _ = fs::remove_file(state.join("ready.json"));
    result?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn batching_avoids_fractional_refill_spin_without_starving_low_rates() {
        let mut fast = Bucket::new(524288, 4096);
        fast.charge(4095);
        assert!(!fast.write_ready(4096));
        fast.tokens = 4096.0;
        assert!(fast.write_ready(4096));
        assert!(Bucket::new(1, 4096).write_ready(4096));
    }
    #[test]
    fn buffer_compaction_preserves_bytes() {
        let mut b = Buffer::new(8);
        b.data.copy_from_slice(b"abcdefgh");
        b.end = 8;
        b.paused = true;
        b.consume(5);
        assert!(!b.paused);
        b.prepare();
        assert_eq!(&b.data[..b.end], b"fgh");
    }
    #[test]
    fn token_bucket_caps_burst_and_debits_actual_bytes() {
        let mut b = Bucket::new(100, 10);
        b.charge(7);
        assert_eq!(b.available(), 3);
        b.refill(b.updated + Duration::from_secs(10));
        assert_eq!(b.available(), 10);
    }
}
