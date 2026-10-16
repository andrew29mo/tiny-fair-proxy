#!/usr/bin/env python3
"""Recompute metrics from all retained observations; reject selective/malformed reports."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import payload, render, source_manifest


def close(a, b):
    assert math.isfinite(a) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10), (a,b)


def verify(report, current_source=True):
    assert report['schema_version'] == 1 and report['status'] == 'passed'
    trials = report['trials']
    assert trials and len(trials) % 8 == 0
    expected = {(b, d, tuple(w), m) for b in range(len(trials)//8) for d in ['upload','download'] for w in [[1,1],[1,3]] for m in ['connection_rr','tenant_fair']}
    identities = [(t['block'],t['direction'],tuple(t['weights']),t['mode']) for t in trials]
    assert len(set(identities)) == len(identities) and set(identities) == expected
    assert report['schedule']['arrival_offsets_s'] == [0,.005,.010,.015,.020]
    for trial in trials:
        work = trial['workload']
        assert work == dict(flow_count=5, tenant_connections=[1,4], bytes_per_flow=524288, rate_bytes_per_sec=524288, window_s=[.4,1.4])
        assert len(trial['flows']) == len(trial['receiver_traces']) == 5
        counts=[]
        for i,(flow,trace) in enumerate(zip(trial['flows'],trial['receiver_traces'])):
            assert flow['index']==i and flow['tenant']==(0 if i==0 else 1)
            assert flow['bytes']==work['bytes_per_flow']
            assert flow['sha256']==hashlib.sha256(payload(i, flow['bytes'])).hexdigest()
            close(flow['planned_s'], i*.005)
            assert flow['issued_s'] >= flow['planned_s'] and flow['finished_s'] > flow['issued_s']
            assert trace and all(isinstance(n,int) and 0<n<=16384 and t>=flow['issued_s'] and t<=flow['finished_s'] for t,n in trace)
            assert all(trace[j][0]<=trace[j+1][0] for j in range(len(trace)-1))
            assert sum(n for t,n in trace)==flow['bytes']
            counts.append(sum(n for t,n in trace if .4<t<=1.4))
        totals=[counts[0],sum(counts[1:])]
        assert totals==trial['receiver_window_bytes'] and sum(totals)>0
        active=all(any(t<=.4 for t,n in trace) and any(t>1.4 for t,n in trace) for trace in trial['receiver_traces'])
        assert active==trial['fairness_window_all_flows_active']
        weights=trial['weights']
        shares=[n/sum(totals) for n in totals]
        target=[w/sum(weights) for w in weights]
        for a,b in zip(shares,trial['receiver_window_shares']):close(a,b)
        for a,b in zip(target,trial['target_shares']):close(a,b)
        normal=[totals[i]/weights[i] for i in range(2)]
        close(trial['weighted_jain'],sum(normal)**2/(2*sum(n*n for n in normal)))
        close(trial['max_share_error'],max(abs(a-b) for a,b in zip(shares,target)))
        elapsed=max(f['finished_s'] for f in trial['flows'])
        close(trial['elapsed_s'],elapsed)
        close(trial['throughput_mib_s'],5*work['bytes_per_flow']/elapsed/1048576)
        for fct,f in zip(trial['flow_completion_s'],trial['flows']):close(fct,f['finished_s']-f['planned_s'])
        close(trial['max_issue_lag_s'],max(f['issued_s']-f['planned_s'] for f in trial['flows']))
        samples=trial['proxy_samples']
        assert len(samples)>10 and all(s['rss']>0 and s['cpu']>=0 for s in samples)
        assert trial['peak_sampled_proxy_rss_bytes']==max(s['rss'] for s in samples)
        close(trial['sampled_proxy_cpu_seconds'],max(s['cpu'] for s in samples)-min(s['cpu'] for s in samples))
        m=trial['proxy_metrics']
        assert m['accepted']==m['completed']==m['peak_connections']==5
        assert all(m[k]==0 for k in ['rejected','io_errors','connect_errors','connect_timeouts','idle_timeouts','forced_drain','current_connections'])
        assert m['reserved_payload_bytes']==8*2*16384 and m['peak_queued_bytes']<=m['reserved_payload_bytes']
        for i,count in enumerate([1,4]):
            forwarded=[count*(work['bytes_per_flow']+2),count*32] if trial['direction']=='upload' else [count*2,count*work['bytes_per_flow']]
            assert m['tenants'][i]['forwarded']==forwarded
    if current_source:
        assert report['source_files']==source_manifest(), 'source manifest differs; regenerate measurements'
    return len(trials)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('directory',type=Path)
    args=ap.parse_args()
    r=json.loads((args.directory/'report.json').read_text())
    n=verify(r)
    assert (args.directory/'report.html').read_text()==render(r), 'HTML differs from JSON'
    print(f'Checked all {n} trials: full grid, exact bytes, common schedule, receiver traces, fairness, throughput, process samples, accounting and canonical HTML.')


if __name__=='__main__':main()
