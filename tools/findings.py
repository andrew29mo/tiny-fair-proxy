#!/usr/bin/env python3
"""Generate README measurements from every retained trial, without selecting winners."""
import argparse
import json
from pathlib import Path
import statistics
from check_report import verify


def findings(r):
    lines=['<!-- measured:start -->', '## Measured results', '',
           'Native macOS ARM64 loopback; 3 randomized paired blocks, 24 trials. Each trial',
           'completes the same five 512 KiB flows, scheduled at 0/5/10/15/20 ms, with a',
           '512 KiB/s global cap in each direction and a 4 KiB burst. Tenant A has one',
           'connection; B has four. Fairness uses receiver bytes during 0.4–1.4 seconds.',
           'Every trial is retained. Ranges below are observed min–max, not confidence intervals.', '',
           '| Direction | A:B weight | Mode | A share %, median [range] | Weighted Jain, median | Throughput MiB/s, median | Proxy peak RSS MiB, median |',
           '|---|---|---|---:|---:|---:|---:|']
    for d in ['upload','download']:
        for w in [[1,1],[1,3]]:
            for m in ['connection_rr','tenant_fair']:
                ts=[t for t in r['trials'] if t['direction']==d and t['weights']==w and t['mode']==m]
                shares=[100*t['receiver_window_shares'][0] for t in ts]
                median=lambda k: statistics.median(t[k] for t in ts)
                lines.append(f'| {d} | {w[0]}:{w[1]} | {m} | {statistics.median(shares):.1f} [{min(shares):.1f}, {max(shares):.1f}] | {median("weighted_jain"):.3f} | {median("throughput_mib_s"):.3f} | {median("peak_sampled_proxy_rss_bytes")/1048576:.2f} |')
    active=sum(t['fairness_window_all_flows_active'] for t in r['trials'])
    lag=max(t['max_issue_lag_s'] for t in r['trials'])
    lines += ['',f'All-flow-active windows: **{active}/{len(r["trials"])}**. Maximum measured issue lag: **{lag*1000:.2f} ms**.',
              '', 'This is a fairness trade-off under an intentionally shaped local bottleneck,',
              'not an unshaped throughput result or a speedup over NGINX/Envoy/HAProxy.',
              'Peak RSS is sampled for the proxy process only; kernel socket buffers and',
              'peer processes are excluded. The fixed payload reservation is 256 KiB in',
              'both modes. Linux/VM results are not inferred from native macOS measurements.',
              '', '[Full JSON](results/native-macos-arm64/report.json) · [HTML report](results/native-macos-arm64/report.html)',
              '<!-- measured:end -->']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    r=json.loads((root/'results/native-macos-arm64/report.json').read_text())
    verify(r)
    assert len(r['trials'])==24
    section=findings(r)
    readme=root/'README.md';text=readme.read_text()
    if '<!-- measured:start -->' in text:
        start=text.index('<!-- measured:start -->');end=text.index('<!-- measured:end -->')+len('<!-- measured:end -->')
        if args.check: assert text[start:end]==section
        else: readme.write_text(text[:start]+section+text[end:])
    else:
        assert not args.check
        readme.write_text(text.replace('Performance results and measured limitations will be added after formal execution.',section))
    print('README measurement section matches all retained trials.')


if __name__=='__main__':main()
