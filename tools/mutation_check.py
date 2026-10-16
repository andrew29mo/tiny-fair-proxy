#!/usr/bin/env python3
"""Compile deliberate faults into the production relay; require behavioral failures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'src/main.rs').read_text()
faults=[
    ('premature_half_close','c.eof[d] && c.buffers[d].len() == 0 && !c.fin_sent[d]', 'c.eof[d] && !c.fin_sent[d]', 'test_proxy.py'),
    ('ignore_tenant_weights','self.cfg.quantum_bytes * self.cfg.tenants[t].weight', 'self.cfg.quantum_bytes', 'test_fairness.py'),
    ('discard_visit_at_empty_staging_buffer','self.refill_empty(d, Some(t));','/* deliberately skip staging refill */','test_review_regressions.ReviewRegressions.test_small_buffer_large_quantum_preserves_weight_both_directions'),
    ('do_not_charge_tokens','self.buckets[d].charge(written);', 'self.buckets[d].charge(0);', 'test_proxy.py'),
]
results=[]
for name,old,new,pattern in faults:
    assert source.count(old)==1,(name,'mutation anchor changed')
    with tempfile.TemporaryDirectory(dir=ROOT/'results/local',prefix='fault-') as tmp:
        tmp=Path(tmp)
        (tmp/'src').mkdir()
        for f in ['Cargo.toml','Cargo.lock','rust-toolchain.toml','build.rs']:shutil.copy2(ROOT/f,tmp/f)
        (tmp/'src/main.rs').write_text(source.replace(old,new))
        env=os.environ.copy()
        env['CARGO_TARGET_DIR']=str(ROOT/'results/local/mutation-target')
        build=subprocess.run([str(ROOT/'tools/rust-env'),'cargo','build','--release','--locked','--manifest-path',str(tmp/'Cargo.toml')],env=env,text=True,capture_output=True,timeout=120)
        assert build.returncode==0,build.stderr
        env['PROXY_ALLOW_FAULT_BUILD']='1'
        env['PROXY_BINARY']=str(ROOT/'results/local/mutation-target/release/tiny-fair-proxy')
        env['PYTHONPATH']=str(ROOT/'tests')
        selection=['discover','-s','tests','-p',pattern,'-v'] if pattern.endswith('.py') else [pattern,'-v']
        run=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','unittest']+selection,cwd=ROOT,env=env,text=True,capture_output=True,timeout=90)
        text=run.stdout+run.stderr
        (ROOT/'results/local'/f'mutation-{name}.txt').write_text(text)
        assert run.returncode!=0 and 'AssertionError' in text and 'FAILED (' in text and 'Ran ' in text,(name,text)
        results.append(dict(fault=name,result='behavioral-test-failed-as-required',test_file=pattern))
        print(name+': detected by actual executable tests',flush=True)
(ROOT/'results/local/mutations.json').write_text(json.dumps(results,indent=2)+'\n')
