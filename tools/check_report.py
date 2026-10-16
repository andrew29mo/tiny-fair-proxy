#!/usr/bin/env python3
"""Recompute all observations against an explicit plan and actual runtime identity."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import payload, render, source_manifest


def close(a, b):
    assert isinstance(a,(int,float)) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10),(a,b)


def ledger(m):
    reasons=['completed','io_errors','connect_errors','connect_timeouts','idle_timeouts','forced_drain','current_connections']
    assert all(type(m[k]) is int and m[k]>=0 for k in reasons+['accepted','rejected'])
    assert m['accepted']==sum(t['accepted'] for t in m['tenants']) and m['rejected']==sum(t['rejected'] for t in m['tenants'])
    assert m['accepted']==sum(m[k] for k in reasons), 'connection outcome ledger does not balance'
    for d in range(2):
        assert m['received'][d]==m['forwarded'][d]+m['discarded'][d]+m['queued_bytes'][d]
        for field in ['received','forwarded','discarded','queued_bytes']:
            assert len(m[field])==2 and all(isinstance(n,int) and n>=0 for n in m[field])
            assert m[field][d]==sum(t[field][d] for t in m['tenants'])
        for t in m['tenants']:
            assert t['received'][d]==t['forwarded'][d]+t['discarded'][d]+t['queued_bytes'][d]
    assert m['peak_queued_bytes']<=m['reserved_payload_bytes']


def verify(report, current_source=True):
    assert report['schema_version']==2 and report['status']=='passed'
    blocks=report['plan']['blocks']
    assert isinstance(blocks,int) and blocks>=1 and report['plan']['seed']==1642
    expected=[];rng=random.Random(1642)
    for b in range(blocks):
        for w in [[1,1],[1,3]]:
            for d in ['upload','download']:
                modes=['connection_rr','tenant_fair'];rng.shuffle(modes)
                expected.extend((b,d,tuple(w),m) for m in modes)
    trials=report['trials']
    assert len(trials)==blocks*8 and [(t['block'],t['direction'],tuple(t['weights']),t['mode']) for t in trials]==expected
    assert report['schedule']==dict(seed=1642,arrival_offsets_s=[0,.005,.010,.015,.020])
    identity=report['binary_identity']
    assert identity['schema_version']==1 and identity['profile']=='release' and identity['rustc'] and identity['target']
    assert identity['files']=={p:h for p,h in report['source_files'].items() if p in ['Cargo.toml','Cargo.lock','build.rs'] or p.startswith('src/')}
    assert len(report['binary_sha256'])==64
    for t in trials:
        w=t['workload']
        assert w==dict(flow_count=5,tenant_connections=[1,4],bytes_per_flow=524288,rate_bytes_per_sec=524288,window_s=[.4,1.4])
        assert t['binary_identity']==identity and t['binary_sha256']==report['binary_sha256']
        cfg=t['actual_config'];tenants=cfg['tenants']
        assert len(tenants)==2 and tenants[0]['backend']==tenants[1]['backend']
        assert tenants[0]['backend'].startswith('127.0.0.1:') and 0<int(tenants[0]['backend'].split(':')[1])<65536
        assert tenants==[dict(name=chr(97+i),listen='127.0.0.1:0',backend=tenants[0]['backend'],weight=n) for i,n in enumerate(t['weights'])]
        assert {k:v for k,v in cfg.items() if k!='tenants'}==dict(mode=t['mode'],rate_bytes_per_sec=524288,burst_bytes=4096,quantum_bytes=4096,buffer_bytes=16384,max_connections=8,max_connections_per_tenant=6,connect_timeout_ms=1000,idle_timeout_ms=30000,drain_timeout_ms=2000)
        for key in ['flows','receiver_traces','flow_completion_s']:assert len(t[key])==5
        for key in ['receiver_window_bytes','receiver_window_shares','target_shares']:assert len(t[key])==2
        counts=[]
        for i,(f,trace) in enumerate(zip(t['flows'],t['receiver_traces'])):
            assert f['index']==i and f['tenant']==(0 if i==0 else 1) and f['bytes']==524288
            assert f['sha256']==hashlib.sha256(payload(i,f['bytes'])).hexdigest()
            close(f['planned_s'],i*.005)
            assert f['issued_s']>=f['planned_s'] and f['finished_s']>f['issued_s']
            assert trace and all(isinstance(n,int) and 0<n<=65536 and f['issued_s']<=stamp<=f['finished_s'] for stamp,n in trace)
            assert all(a[0]<=b[0] for a,b in zip(trace,trace[1:]))
            assert sum(n for stamp,n in trace)==f['bytes']
            counts.append(sum(n for stamp,n in trace if .4<stamp<=1.4))
        totals=[counts[0],sum(counts[1:])];total=sum(totals)
        assert totals==t['receiver_window_bytes']
        active=all(any(stamp<=.4 for stamp,n in tr) and any(stamp>1.4 for stamp,n in tr) for tr in t['receiver_traces'])
        assert active==t['fairness_window_all_flows_active']
        shares=[n/total for n in totals] if total else [0.,0.]
        target=[n/sum(t['weights']) for n in t['weights']]
        for a,b in zip(shares,t['receiver_window_shares']):close(a,b)
        for a,b in zip(target,t['target_shares']):close(a,b)
        norm=[totals[i]/t['weights'][i] for i in range(2)]
        if total:close(t['weighted_jain'],sum(norm)**2/(2*sum(n*n for n in norm)))
        else:assert t['weighted_jain'] is None
        close(t['max_share_error'],max(abs(a-b) for a,b in zip(shares,target)))
        elapsed=max(f['finished_s'] for f in t['flows'])
        close(t['elapsed_s'],elapsed);close(t['throughput_mib_s'],2.5/elapsed)
        assert elapsed>=(5*524288-4096)/524288*.95
        for fct,f in zip(t['flow_completion_s'],t['flows']):close(fct,f['finished_s']-f['planned_s'])
        close(t['max_issue_lag_s'],max(f['issued_s']-f['planned_s'] for f in t['flows']))
        samples=t['proxy_samples']
        assert len(samples)>10 and all(isinstance(s['rss'],int) and s['rss']>0 and s['cpu']>=0 and math.isfinite(s['t']) for s in samples)
        assert all(a['t']<=b['t'] and a['cpu']<=b['cpu'] for a,b in zip(samples,samples[1:]))
        assert samples[0]['t']<=0 and samples[-1]['t']>=elapsed
        assert t['peak_sampled_proxy_rss_bytes']==max(s['rss'] for s in samples)
        assert t['baseline_proxy_rss_bytes']==samples[0]['rss']
        assert t['peak_proxy_rss_growth_bytes']==max(s['rss'] for s in samples)-samples[0]['rss']
        close(t['sampled_proxy_cpu_seconds'],samples[-1]['cpu']-samples[0]['cpu'])
        close(t['max_sample_gap_s'],max(b['t']-a['t'] for a,b in zip(samples,samples[1:])))
        m=t['proxy_metrics'];ledger(m)
        assert m['accepted']==m['completed']==m['peak_connections']==5
        assert all(m[k]==0 for k in ['rejected','io_errors','connect_errors','connect_timeouts','idle_timeouts','forced_drain','current_connections'])
        assert m['reserved_payload_bytes']==262144 and m['discarded']==m['queued_bytes']==[0,0]
        for i,count in enumerate([1,4]):
            forwarded=[count*(524288+2),count*32] if t['direction']=='upload' else [count*2,count*524288]
            assert m['tenants'][i]['forwarded']==forwarded
    if current_source:assert report['source_files']==source_manifest(),'source manifest differs; regenerate measurements'
    return len(trials)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args()
    r=json.loads((args.directory/'report.json').read_text());n=verify(r)
    assert (args.directory/'report.html').read_text()==render(r),'HTML differs from JSON'
    print(f'Checked all {n} planned trials: runtime identity/config, full bytes/outcomes, fairness, throughput, sample coverage, RSS and canonical HTML.')


if __name__=='__main__':main()
