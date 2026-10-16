"""Actual TCP peers and actual release executable; no replacement relay."""
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('PROXY_BINARY', ROOT / 'target/release/tiny-fair-proxy'))


def wait_for(fn, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('condition timed out')


def receive_all(s):
    chunks = []
    while True:
        data = s.recv(65536)
        if not data:
            return b''.join(chunks)
        chunks.append(data)


class Backend:
    def __init__(self, handler):
        self.handler = handler
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(128)
        self.socket.settimeout(.1)
        self.address = '%s:%s' % self.socket.getsockname()
        self.stop = threading.Event()
        self.errors = queue.Queue()
        self.clients = []
        self.threads = []
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.stop.is_set():
            try:
                client, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            client.settimeout(10)
            self.clients.append(client)
            thread = threading.Thread(target=self._handle, args=(client,), daemon=True)
            self.threads.append(thread)
            thread.start()

    def _handle(self, s):
        try:
            self.handler(s)
        except BaseException as error:
            if not self.stop.is_set():
                self.errors.put(repr(error))
        finally:
            s.close()

    def close(self):
        self.stop.set()
        self.socket.close()
        for s in self.clients:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        self.thread.join(2)
        for t in self.threads:
            t.join(2)
        assert not self.thread.is_alive() and all(not t.is_alive() for t in self.threads), 'backend thread leaked'


class Proxy:
    def __init__(self, backend, **overrides):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        tenant_overrides = overrides.pop('tenants', None)
        self.config = dict(mode='tenant_fair', rate_bytes_per_sec=100_000_000,
                           burst_bytes=65536, quantum_bytes=4096, buffer_bytes=16384,
                           max_connections=16, max_connections_per_tenant=12,
                           connect_timeout_ms=1000, idle_timeout_ms=10000,
                           drain_timeout_ms=2000,
                           tenants=tenant_overrides or [dict(name=n, listen='127.0.0.1:0', backend=backend, weight=1) for n in ['a', 'b']])
        self.config.update(overrides)
        (self.directory / 'config.json').write_text(json.dumps(self.config))
        self.log = (self.directory / 'stderr.txt').open('w+')
        self.process = subprocess.Popen([str(BINARY), str(self.directory / 'config.json'), str(self.directory / 'state')], stdout=self.log, stderr=self.log)
        try:
            def ready():
                if self.process.poll() is not None:
                    self.log.seek(0)
                    raise AssertionError(self.log.read())
                path = self.directory / 'state/ready.json'
                return json.loads(path.read_text()) if path.exists() else None
            self.ready = wait_for(ready)
        except BaseException:
            self.close(force=True)
            raise

    def connect(self, tenant=0):
        host, port = self.ready['listeners'][tenant].rsplit(':', 1)
        s = socket.create_connection((host, int(port)), 3)
        s.settimeout(10)
        return s

    def metrics(self):
        return json.loads((self.directory / 'state/metrics.json').read_text())

    def terminate(self):
        self.process.send_signal(signal.SIGTERM)

    def finish(self, timeout=6):
        assert self.process.wait(timeout) == 0
        assert not (self.directory / 'state/ready.json').exists()
        return self.metrics()

    def close(self, force=False):
        if self.process.poll() is None:
            self.process.kill() if force else self.terminate()
            try:
                self.process.wait(6)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(3)
                raise AssertionError('proxy did not exit within deadline')
        self.log.close()
        self.temp.cleanup()
