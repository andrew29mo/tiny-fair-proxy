import hashlib
import json
import socket
import struct
import subprocess
import threading
import time
import unittest
from support import Backend, Proxy, BINARY, receive_all, wait_for


class ProductionProxyTests(unittest.TestCase):
    def backend(self, handler):
        b = Backend(handler)
        self.addCleanup(b.close)
        return b

    def proxy(self, b, **kw):
        p = Proxy(b.address, **kw)
        def cleanup():
            try:
                p.terminate() if p.process.poll() is None else None
                m = p.finish() if p.process.poll() is None else p.metrics()
                self.assertEqual(m['accepted'],sum(m[k] for k in ['completed','io_errors','connect_errors','connect_timeouts','idle_timeouts','forced_drain','current_connections']))
                for d in range(2):
                    self.assertEqual(m['received'][d],m['forwarded'][d]+m['discarded'][d]+m['queued_bytes'][d])
                    self.assertEqual(m['queued_bytes'][d],0)
            finally:
                p.close()
        self.addCleanup(cleanup)
        return p

    def test_half_close_preserves_large_response_and_byte_order(self):
        payload = hashlib.shake_256(b'half-close-upload').digest(524291)
        response = hashlib.shake_256(b'half-close-response').digest(262151)
        def handle(s):
            self.assertEqual(receive_all(s), payload)
            for offset in range(0, len(response), 997):
                s.sendall(response[offset:offset+997])
        b = self.backend(handle)
        p = self.proxy(b)
        with p.connect() as s:
            for offset in range(0, len(payload), 1237):
                s.sendall(payload[offset:offset+1237])
            s.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_all(s), response)
        wait_for(lambda: p.metrics()['completed'] == 1)
        self.assertTrue(b.errors.empty(), list(b.errors.queue))

    def test_simultaneous_bidirectional_streams(self):
        payload = hashlib.shake_256(b'duplex-upload').digest(1004003)
        response = hashlib.shake_256(b'duplex-download').digest(1050007)
        def handle(s):
            errors = []
            def send():
                try:
                    s.sendall(response)
                    s.shutdown(socket.SHUT_WR)
                except BaseException as e:
                    errors.append(e)
            t = threading.Thread(target=send)
            t.start()
            self.assertEqual(receive_all(s), payload)
            t.join(5)
            self.assertFalse(t.is_alive())
            self.assertEqual(errors, [])
        b = self.backend(handle)
        p = self.proxy(b)
        with p.connect() as s:
            errors = []
            def send():
                try:
                    s.sendall(payload)
                    s.shutdown(socket.SHUT_WR)
                except BaseException as e:
                    errors.append(e)
            t = threading.Thread(target=send)
            t.start()
            self.assertEqual(receive_all(s), response)
            t.join(5)
            self.assertFalse(t.is_alive())
            self.assertEqual(errors, [])
        wait_for(lambda: p.metrics()['completed'] == 1)
        self.assertTrue(b.errors.empty(), list(b.errors.queue))

    def test_slow_consumer_backpressure_and_other_tenant_progress(self):
        release = threading.Event()
        self.addCleanup(release.set)
        data = hashlib.shake_256(b'slow-upload').digest(1024*1024+3)
        def slow(s):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
            release.wait(5)
            actual = receive_all(s)
            self.assertEqual(actual, data)
            s.sendall(hashlib.sha256(actual).digest())
        b = self.backend(slow)
        fast = self.backend(lambda s: s.sendall(receive_all(s)))
        tenants = [dict(name='slow', listen='127.0.0.1:0', backend=b.address, weight=1),
                   dict(name='fast', listen='127.0.0.1:0', backend=fast.address, weight=1)]
        p = self.proxy(b, tenants=tenants)
        s = p.connect()
        self.addCleanup(s.close)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)
        sent = threading.Event()
        errors = []
        def push():
            try:
                s.sendall(data)
                sent.set()
                s.shutdown(socket.SHUT_WR)
                self.assertEqual(receive_all(s), hashlib.sha256(data).digest())
            except BaseException as error:
                errors.append(repr(error))
        t = threading.Thread(target=push)
        t.start()
        wait_for(lambda: p.metrics()['paused_reads'] > 0)
        with p.connect(1) as f:
            f.sendall(b'fast-peer')
            f.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_all(f), b'fast-peer')
        m = p.metrics()
        self.assertLessEqual(m['peak_queued_bytes'], m['reserved_payload_bytes'])
        self.assertLessEqual(m['tenants'][0]['peak_queued_bytes'], 2*p.config['buffer_bytes'])
        release.set()
        t.join(12)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(sent.is_set())
        self.assertTrue(b.errors.empty(),list(b.errors.queue))
        wait_for(lambda: p.metrics()['completed']==2)
        self.assertEqual(p.metrics()['discarded'],[0,0])

    def test_per_tenant_and_global_overload_reject_without_backend_work(self):
        release = threading.Event()
        self.addCleanup(release.set)
        b = self.backend(lambda s: release.wait(5))
        p = self.proxy(b, max_connections=2, max_connections_per_tenant=1)
        a = p.connect(0)
        self.addCleanup(a.close)
        wait_for(lambda: p.metrics()['accepted'] == 1)
        with p.connect(0) as rejected:
            try:
                self.assertEqual(rejected.recv(1), b'')
            except ConnectionResetError:
                pass
        c = p.connect(1)
        self.addCleanup(c.close)
        wait_for(lambda: p.metrics()['accepted'] == 2)
        with p.connect(1) as rejected:
            try:
                self.assertEqual(rejected.recv(1), b'')
            except ConnectionResetError:
                pass
        wait_for(lambda: p.metrics()['rejected'] == 2)
        self.assertEqual(p.metrics()['peak_connections'], 2)
        self.assertEqual(len(b.clients), 2)
        release.set()

    def test_graceful_shutdown_drains_existing_half_closed_connection(self):
        received = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        response = b'reply' * 40000
        def handle(s):
            self.assertEqual(receive_all(s), b'request')
            received.set()
            release.wait(3)
            s.sendall(response)
        b = self.backend(handle)
        p = self.proxy(b)
        with p.connect() as s:
            s.sendall(b'request')
            s.shutdown(socket.SHUT_WR)
            self.assertTrue(received.wait(3))
            p.terminate()
            time.sleep(.05)
            with self.assertRaises(OSError):
                p.connect()
            release.set()
            self.assertEqual(receive_all(s), response)
        m = p.finish()
        self.assertEqual(m['forced_drain'], 0)
        self.assertEqual(m['completed'], 1)
        self.assertEqual(m['current_connections'], 0)

    def test_shutdown_deadline_forces_idle_connection(self):
        release = threading.Event()
        self.addCleanup(release.set)
        b = self.backend(lambda s: release.wait(5))
        p = self.proxy(b, drain_timeout_ms=100)
        with p.connect():
            wait_for(lambda: p.metrics()['accepted'] == 1)
            p.terminate()
            m = p.finish()
        self.assertEqual(m['forced_drain'], 1)
        self.assertEqual(m['current_connections'], 0)
        release.set()

    def test_idle_timeout_returns_reserved_slot(self):
        b = self.backend(receive_all)
        p = self.proxy(b, idle_timeout_ms=150, max_connections=1, max_connections_per_tenant=1)
        with p.connect() as s:
            self.assertEqual(s.recv(1), b'')
        wait_for(lambda: p.metrics()['idle_timeouts'] == 1)
        with p.connect() as s:
            s.shutdown(socket.SHUT_WR)
            self.assertEqual(s.recv(1), b'')
        wait_for(lambda: p.metrics()['accepted'] == 2)

    def test_backend_refusal_cleans_connection(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        address = '%s:%s' % sock.getsockname()
        sock.close()
        p = Proxy(address)
        self.addCleanup(p.close)
        with p.connect() as s:
            try:
                self.assertEqual(s.recv(1), b'')
            except ConnectionResetError:
                pass
        wait_for(lambda: p.metrics()['connect_errors'] == 1)
        self.assertEqual(p.metrics()['current_connections'], 0)

    def test_rate_budget_counts_successful_writes(self):
        data = hashlib.shake_256(b'budget').digest(131072)
        b = self.backend(lambda s: s.sendall(hashlib.sha256(receive_all(s)).digest()))
        p = self.proxy(b, rate_bytes_per_sec=32768, burst_bytes=4096)
        started = time.monotonic()
        with p.connect() as s:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_all(s), hashlib.sha256(data).digest())
        # This is a maximum-rate contract, not a minimum-performance assertion.
        minimum = (len(data)-4096)/32768
        self.assertGreaterEqual(time.monotonic()-started, minimum*.95)

    def test_global_limit_independent_of_tenant_limit(self):
        release = threading.Event()
        self.addCleanup(release.set)
        b = self.backend(lambda s: release.wait(5))
        p = self.proxy(b, max_connections=2, max_connections_per_tenant=2)
        clients = [p.connect(0), p.connect(0)]
        for s in clients:
            self.addCleanup(s.close)
        wait_for(lambda: p.metrics()['accepted'] == 2)
        with p.connect(1) as rejected:
            try:
                self.assertEqual(rejected.recv(1), b'')
            except ConnectionResetError:
                pass
        wait_for(lambda: p.metrics()['rejected'] == 1)
        self.assertEqual(p.metrics()['tenants'][1]['accepted'], 0)
        release.set()

    def test_reset_does_not_kill_proxy(self):
        b = self.backend(lambda s: s.sendall(receive_all(s)))
        b.allow_peer_errors = True  # This peer is intentionally reset mid-stream.
        p = self.proxy(b)
        s = p.connect()
        s.sendall(b'x' * 100000)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        s.close()
        wait_for(lambda: p.metrics()['io_errors'] > 0)
        with p.connect(1) as s:
            s.sendall(b'still-alive')
            s.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_all(s), b'still-alive')

    def test_duplicate_state_directory_fails_without_removing_ready(self):
        b = self.backend(receive_all)
        p = self.proxy(b)
        result = subprocess.run([str(BINARY), str(p.directory/'config.json'), str(p.directory/'state')], capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'already in use', result.stderr)
        self.assertTrue((p.directory/'state/ready.json').exists())

    def test_invalid_configuration_fails_closed(self):
        b = self.backend(receive_all)
        for kw in [dict(mode='typo'), dict(burst_bytes=0), dict(buffer_bytes=1), dict(max_connections=10000)]:
            with self.subTest(kw=kw), self.assertRaises(AssertionError):
                Proxy(b.address, **kw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
