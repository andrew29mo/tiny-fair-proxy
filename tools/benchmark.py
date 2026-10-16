#!/usr/bin/env python3
"""Open-loop connection schedule, fixed bytes; actual peers verify every byte."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from support import Backend, Proxy, BINARY, receive_all, wait_for


def payload(index, size):
    block = hashlib.sha256(('flow-%d' % index).encode()).digest()
    return (block * ((size+31)//32))[:size]


def source_manifest():
    names = ['Cargo.toml', 'Cargo.lock'] + [str(p.relative_to(ROOT)) for group in ['src', 'tests', 'tools'] for p in (ROOT/group).rglob('*.rs' if group == 'src' else '*.py')]
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(names)}


def run_trial(mode, weights, direction, size, rate):
    traces = [[] for _ in range(5)]
    errors = []
    origin = [None]
    config_ready = threading.Event()
    connections = []
    def backend(s):
        header = bytearray()
        while not header.endswith(b'\n'):
            part = s.recv(1)
            if not part:
                raise AssertionError('header EOF')
            header.extend(part)
            if len(header) > 128:
                raise AssertionError('oversized header')
        index = int(header)
        expected = payload(index, size)
        if direction == 'upload':
            data = bytearray()
            while True:
                part = s.recv(16384)
                if not part:
                    break
                data.extend(part)
                traces[index].append([time.monotonic()-origin[0], len(part)])
            assert data == expected, 'upstream byte mismatch'
            s.sendall(hashlib.sha256(data).digest())
        else:
            assert receive_all(s) == b''
            s.sendall(expected)
            s.shutdown(1)
    b = Backend(backend)
    tenants = [dict(name=chr(97+i), listen='127.0.0.1:0', backend=b.address, weight=w) for i, w in enumerate(weights)]
    p = None
    try:
        p = Proxy(b.address, mode=mode, tenants=tenants, rate_bytes_per_sec=rate,
                  burst_bytes=4096, quantum_bytes=4096, max_connections=8,
                  max_connections_per_tenant=6, buffer_bytes=16384,
                  idle_timeout_ms=30000, drain_timeout_ms=2000)
        # All sockets established before the common start; the generator records actual issue lag.
        for i in range(5):
            connections.append(p.connect(0 if i == 0 else 1))
        wait_for(lambda: p.metrics()['accepted'] == 5)
        process = psutil.Process(p.process.pid)
        samples = []
        stop = threading.Event()
        def sample():
            while not stop.wait(.01):
                try:
                    cpu = process.cpu_times()
                    samples.append(dict(t=time.monotonic()-origin[0], rss=process.memory_info().rss, cpu=cpu.user+cpu.system))
                except psutil.NoSuchProcess:
                    break
        results = [None]*5
        origin[0] = time.monotonic()+.1
        def client(index):
            s = connections[index]
            planned = index * .005
            time.sleep(max(0, origin[0]+planned-time.monotonic()))
            issued = time.monotonic()-origin[0]
            expected = payload(index, size)
            s.sendall(('%d\n' % index).encode())
            if direction == 'upload':
                s.sendall(expected)
                s.shutdown(1)
                assert receive_all(s) == hashlib.sha256(expected).digest(), 'ack mismatch'
            else:
                s.shutdown(1)
                data = bytearray()
                while True:
                    part = s.recv(16384)
                    if not part:
                        break
                    data.extend(part)
                    traces[index].append([time.monotonic()-origin[0], len(part)])
                assert data == expected, 'downstream byte mismatch'
            results[index] = dict(index=index, tenant=0 if index==0 else 1,
                                  planned_s=planned, issued_s=issued,
                                  finished_s=time.monotonic()-origin[0],
                                  bytes=size, sha256=hashlib.sha256(expected).hexdigest())
        sampler = threading.Thread(target=sample)
        sampler.start()
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(client, i) for i in range(5)]
                for future in futures:
                    future.result(timeout=25)
        finally:
            stop.set()
            sampler.join(2)
        wait_for(lambda: p.metrics()['completed'] == 5)
        p.terminate()
        metrics = p.finish()
        assert b.errors.empty(), list(b.errors.queue)
        assert all(results)
        # Common 1-second window; require every flow's receiver to have bytes before AND after.
        window = [.4, 1.4]
        active = all(any(t <= window[0] for t,n in trace) and any(t > window[1] for t,n in trace) for trace in traces)
        counts = [sum(n for t,n in trace if window[0] < t <= window[1]) for trace in traces]
        totals = [counts[0], sum(counts[1:])]
        shares = [n/sum(totals) for n in totals]
        target = [w/sum(weights) for w in weights]
        normalized = [totals[i]/weights[i] for i in range(2)]
        jain = sum(normalized)**2/(2*sum(x*x for x in normalized))
        elapsed = max(r['finished_s'] for r in results)-min(r['planned_s'] for r in results)
        return dict(mode=mode, weights=weights, direction=direction, workload=dict(flow_count=5, tenant_connections=[1,4], bytes_per_flow=size, rate_bytes_per_sec=rate, window_s=window),
                    fairness_window_all_flows_active=active, receiver_window_bytes=totals,
                    receiver_window_shares=shares, target_shares=target,
                    weighted_jain=jain, max_share_error=max(abs(a-b) for a,b in zip(shares,target)),
                    throughput_mib_s=(size*5)/elapsed/(1024*1024), elapsed_s=elapsed,
                    flow_completion_s=[r['finished_s']-r['planned_s'] for r in results],
                    max_issue_lag_s=max(r['issued_s']-r['planned_s'] for r in results),
                    peak_sampled_proxy_rss_bytes=max(s['rss'] for s in samples),
                    sampled_proxy_cpu_seconds=max(s['cpu'] for s in samples)-min(s['cpu'] for s in samples),
                    flows=results, receiver_traces=traces, proxy_samples=samples, proxy_metrics=metrics)
    finally:
        for s in connections:
            s.close()
        if p is not None:
            p.close()
        b.close()


def render(report):
    rows = []
    for t in report['trials']:
        shares = ' / '.join('%.1f%%' % (100*x) for x in t['receiver_window_shares'])
        rows.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [t['block'],t['direction'],str(t['weights']),t['mode'],shares,'%.3f'%t['weighted_jain'],'%.3f'%t['throughput_mib_s'],'%.2f'%(t['peak_sampled_proxy_rss_bytes']/1048576),'%.3f'%max(t['flow_completion_s']),str(t['fairness_window_all_flows_active'])])+'</tr>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Tiny Fair Proxy results</title><style>body{font:16px system-ui;margin:2rem;max-width:1200px;color:#172b4d}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:.6rem;border-bottom:1px solid #ccc;text-align:left}code{overflow-wrap:anywhere}</style><h1>Tiny Fair Proxy — measured trade-offs</h1><p>'+html.escape(report['environment']['label'])+'</p><p>Same five flows (tenant A: 1, B: 4), payloads, arrival offsets, rate, burst and buffer budget in both modes. Weighted fairness is measured at receivers during 0.4–1.4 s. All trials retained; inactive windows are labelled, never filtered out. Fixed complete-workload throughput includes tails. RSS is sampled proxy-process RSS, not whole-system or physical memory. Kernel socket buffers and clients/backends are excluded. CPU covers the sampled interval. No universal speedup or hard latency guarantee.</p><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in ['Block','Direction','Weights','Mode','A / B share','Weighted Jain','MiB/s','RSS MiB','Max FCT s','All active'])+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table><p>JSON contains every receiver trace, generator issue lag, process sample and final proxy accounting.</p></html>\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--blocks', type=int, default=3)
    ap.add_argument('--label', required=True)
    args = ap.parse_args()
    assert args.blocks >= 1
    args.output.mkdir(parents=True, exist_ok=True)
    before = source_manifest()
    report = dict(schema_version=1, environment=dict(label=args.label, os=platform.system(), machine=platform.machine(), python=platform.python_version()),
                  source_files=before, binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
                  schedule=dict(seed=1642, arrival_offsets_s=[0,.005,.010,.015,.020]), trials=[], status='running')
    rng = random.Random(1642)
    for block in range(args.blocks):
        for weights in [[1,1],[1,3]]:
            for direction in ['upload','download']:
                modes = ['connection_rr','tenant_fair']
                rng.shuffle(modes)
                for mode in modes:
                    trial = run_trial(mode, weights, direction, 512*1024, 512*1024)
                    trial['block'] = block
                    report['trials'].append(trial)
                    print(json.dumps({k:trial[k] for k in ['block','direction','weights','mode','receiver_window_shares','weighted_jain','fairness_window_all_flows_active']}), flush=True)
                    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    assert before == source_manifest(), 'source changed while measuring'
    report['status'] = 'passed'
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output/'report.html').write_text(render(report))


if __name__ == '__main__':
    main()
