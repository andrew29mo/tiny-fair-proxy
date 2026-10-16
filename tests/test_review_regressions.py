"""Actual-socket regressions for review findings; no alternative relay implementation."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from support import Backend, Proxy, BINARY, ROOT, binary_identity, receive_all, wait_for
sys.path.insert(0,str(ROOT/"tools"))


class ReviewRegressions(unittest.TestCase):
    def test_small_buffer_large_quantum_preserves_weight_both_directions(self):
        for direction in ['upload','download']:
            with self.subTest(direction=direction):
                traces=[[],[]];origin=[0]
                data=[hashlib.shake_256(bytes([i])).digest(262147) for i in range(2)]
                def handler(s):
                    index=int(s.recv(1))
                    if direction=='upload':
                        actual=receive_all(s,on_chunk=lambda part:traces[index].append((time.monotonic()-origin[0],len(part))))
                        self.assertEqual(actual,data[index]);s.sendall(hashlib.sha256(actual).digest())
                    else:
                        self.assertEqual(receive_all(s),b'');s.sendall(data[index])
                b=Backend(handler)
                p=Proxy(b.address,tenants=[dict(name=str(i),listen='127.0.0.1:0',backend=b.address,weight=w) for i,w in enumerate([1,3])],rate_bytes_per_sec=131072,burst_bytes=16384,quantum_bytes=4096,buffer_bytes=1024)
                clients=[p.connect(i) for i in range(2)];errors=[]
                try:
                    wait_for(lambda:p.metrics()['accepted']==2);origin[0]=time.monotonic()+.1
                    def client(i):
                        try:
                            s=clients[i];time.sleep(max(0,origin[0]+i*.005-time.monotonic()))
                            s.sendall(str(i).encode())
                            if direction=='upload':
                                s.sendall(data[i]);s.shutdown(socket.SHUT_WR)
                                self.assertEqual(receive_all(s),hashlib.sha256(data[i]).digest())
                            else:
                                s.shutdown(socket.SHUT_WR)
                                actual=receive_all(s,on_chunk=lambda part:traces[i].append((time.monotonic()-origin[0],len(part))))
                                self.assertEqual(actual,data[i])
                        except BaseException as e:errors.append(repr(e))
                    threads=[threading.Thread(target=client,args=(i,)) for i in range(2)]
                    for t in threads:t.start()
                    for t in threads:t.join(15)
                    self.assertTrue(all(not t.is_alive() for t in threads));self.assertEqual(errors,[])
                    counts=[sum(n for t,n in tr if .4<t<=1.4) for tr in traces]
                    self.assertTrue(all(any(t<=.4 for t,n in tr) and any(t>1.4 for t,n in tr) for tr in traces))
                    self.assertAlmostEqual(counts[0]/sum(counts),.25,delta=.04)
                    self.assertTrue(b.errors.empty(),list(b.errors.queue))
                    wait_for(lambda:p.metrics()['completed']==2)
                finally:
                    for s in clients:s.close()
                    p.close();b.close()

    def test_backend_half_closes_first_while_upload_continues(self):
        upload=hashlib.shake_256(b'after-backend-fin').digest(65539)
        response=b'first-fin'
        def handler(s):
            s.sendall(response);s.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_all(s),upload)
        b=Backend(handler);p=Proxy(b.address,buffer_bytes=1024,burst_bytes=4096)
        try:
            with p.connect() as s:
                self.assertEqual(receive_all(s),response)
                s.sendall(upload);s.shutdown(socket.SHUT_WR)
            wait_for(lambda:p.metrics()['completed']==1)
            self.assertTrue(b.errors.empty(),list(b.errors.queue))
            self.assertEqual(p.metrics()['received'],[len(upload),len(response)])
            self.assertEqual(p.metrics()['discarded'],[0,0])
        finally:p.close();b.close()

    def test_drain_with_queued_tail_is_delivered_and_accounted(self):
        data=hashlib.shake_256(b'drain-tail').digest(98307)
        b=Backend(lambda s:s.sendall(hashlib.sha256(receive_all(s)).digest()))
        p=Proxy(b.address,rate_bytes_per_sec=131072,burst_bytes=4096)
        try:
            with p.connect() as s:
                s.sendall(data);s.shutdown(socket.SHUT_WR)
                wait_for(lambda:sum(p.metrics()['queued_bytes'])>0)
                p.terminate()
                self.assertEqual(receive_all(s),hashlib.sha256(data).digest())
            m=p.finish()
            self.assertEqual(m['received'],[len(data),32]);self.assertEqual(m['forwarded'],m['received'])
            self.assertEqual(m['discarded'],[0,0]);self.assertEqual(m['queued_bytes'],[0,0])
            self.assertEqual(m['forced_drain'],0)
        finally:p.close();b.close()

    def test_forced_drain_accounts_queued_bytes_and_connection(self):
        release=threading.Event()
        b=Backend(lambda s:release.wait(5));p=Proxy(b.address,rate_bytes_per_sec=1024,burst_bytes=1024,drain_timeout_ms=100)
        try:
            with p.connect() as s:
                s.sendall(hashlib.shake_256(b'forced').digest(32771))
                wait_for(lambda:sum(p.metrics()['queued_bytes'])>0)
                p.terminate();m=p.finish()
            self.assertEqual(m['forced_drain'],1);self.assertGreater(sum(m['discarded']),0)
            for d in range(2):self.assertEqual(m['received'][d],m['forwarded'][d]+m['discarded'][d])
            self.assertEqual(m['queued_bytes'],[0,0])
        finally:release.set();p.close();b.close()

    def test_slow_download_does_not_block_other_tenant_and_recovers(self):
        data=hashlib.shake_256(b'slow-download').digest(1048583)
        def big(s):
            self.assertEqual(receive_all(s),b'');s.sendall(data)
        b=Backend(big);fast=Backend(lambda s:s.sendall(receive_all(s)))
        p=Proxy(b.address,tenants=[dict(name='slow',listen='127.0.0.1:0',backend=b.address,weight=1),dict(name='fast',listen='127.0.0.1:0',backend=fast.address,weight=1)])
        try:
            with p.connect() as slow:
                slow.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,32768);slow.shutdown(socket.SHUT_WR)
                wait_for(lambda:p.metrics()['paused_reads']>0)
                with p.connect(1) as f:
                    f.sendall(b'fast');f.shutdown(socket.SHUT_WR);self.assertEqual(receive_all(f),b'fast')
                self.assertEqual(receive_all(slow),data)
            wait_for(lambda:p.metrics()['completed']==2)
            self.assertTrue(b.errors.empty(),list(b.errors.queue));self.assertEqual(p.metrics()['discarded'],[0,0])
        finally:p.close();b.close();fast.close()

    def test_receive_has_absolute_deadline_even_with_dribbling_peer(self):
        a,b=socket.socketpair();stop=threading.Event()
        def drip():
            while not stop.wait(.01):
                try:b.sendall(b'x')
                except OSError:return
        t=threading.Thread(target=drip);t.start()
        try:
            with self.assertRaises((TimeoutError,socket.timeout)):
                receive_all(a,deadline=time.monotonic()+.15)
        finally:stop.set();a.close();b.close();t.join(1)
        self.assertFalse(t.is_alive())

    def test_stale_source_identity_is_rejected(self):
        original=Path.read_bytes
        def changed(path):
            data=original(path)
            return data+b'\n// stale-source probe\n' if path==ROOT/'src/main.rs' else data
        with patch.object(Path,'read_bytes',changed),self.assertRaisesRegex(AssertionError,'does not match'):
            binary_identity()

    def test_optimized_validation_is_refused(self):
        result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/check_report.py'),str(ROOT/'results/native-macos-arm64')],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertIn('optimized Python is refused',result.stderr)


class HarnessRegressions(unittest.TestCase):
    def test_nonzero_proxy_exit_is_not_silently_accepted(self):
        b=Backend(receive_all);p=Proxy(b.address)
        try:
            p.process.kill();p.process.wait(3)
            with self.assertRaisesRegex(AssertionError,'abnormally'):p.close()
        finally:b.close()

    def test_report_failure_overwrites_previous_success(self):
        import benchmark
        for stage in ['build','trial','html']:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp);(path/'report.json').write_text('{"status":"passed"}')
                (path/'report.html').write_text('<h1>old successful result</h1>')
                build_error=RuntimeError('injected failure') if stage=='build' else None
                trial_error=RuntimeError('injected failure') if stage=='trial' else None
                original_write=Path.write_text
                def fail_html_write(p,*args,**kw):
                    if p==path/'report.html':
                        original_write(p,'partial HTML')
                        raise RuntimeError('injected failure')
                    return original_write(p,*args,**kw)
                trial=dict(binary_identity=binary_identity(),direction='upload',weights=[1,1],mode='tenant_fair',receiver_window_shares=[.5,.5],weighted_jain=1.,fairness_window_all_flows_active=True)
                with patch.object(sys,'argv',['benchmark','--output',tmp,'--blocks','1','--label','failure-fixture']),patch.object(benchmark,'build_for_measurement',return_value=binary_identity(),side_effect=build_error),patch.object(benchmark,'run_trial',return_value=trial,side_effect=trial_error),patch.object(benchmark,'render',return_value='<h1>new result</h1>'),patch.object(Path,'write_text',fail_html_write if stage=='html' else original_write):
                    with self.assertRaisesRegex(RuntimeError,'injected failure'):benchmark.main()
                self.assertEqual(json.loads((path/'report.json').read_text())['status'],'failed')
                self.assertFalse((path/'report.html').exists())

    def test_sampling_failure_prevents_successful_trial(self):
        import benchmark
        real_process=benchmark.psutil.Process
        class BrokenSampler:
            def __init__(self,pid):self.inner=real_process(pid);self.calls=0
            def cpu_times(self):return self.inner.cpu_times()
            def memory_info(self):
                self.calls+=1
                if self.calls>1:raise RuntimeError('sampling failure fixture')
                return self.inner.memory_info()
        with patch.object(benchmark.psutil,'Process',BrokenSampler):
            with self.assertRaisesRegex(RuntimeError,'incomplete process sampling'):
                benchmark.run_trial('tenant_fair',[1,1],'upload',65536,524288)

    def test_reused_buffer_slots_do_not_repeat_previous_stream_bytes(self):
        b=Backend(lambda s:s.sendall(hashlib.sha256(receive_all(s)).digest()))
        p=Proxy(b.address,max_connections=1,max_connections_per_tenant=1,buffer_bytes=1024)
        sizes=[17,1027,65413,131089]
        try:
            for i,size in enumerate(sizes):
                data=hashlib.shake_256(str(i).encode()).digest(size)
                with p.connect(i%2) as stream:
                    stream.sendall(data);stream.shutdown(socket.SHUT_WR)
                    self.assertEqual(receive_all(stream),hashlib.sha256(data).digest())
                wait_for(lambda:p.metrics()['completed']==i+1)
            p.terminate();m=p.finish()
            self.assertEqual(m['received'],[sum(sizes),len(sizes)*32]);self.assertEqual(m['received'],m['forwarded'])
            self.assertEqual(m['discarded'],[0,0]);self.assertEqual(m['peak_connections'],1)
        finally:p.close();b.close()
