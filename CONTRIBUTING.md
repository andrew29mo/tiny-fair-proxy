# Development

Install Rust 1.99.1 and Python 3.12, create `.venv`, and install
`requirements-dev.txt`. Run `PYTHON=.venv/bin/python ./tools/validate` to build and
test the actual release executable. `cargo fmt --check` and
`cargo clippy --locked --all-targets -- -D warnings` are additional checks.

Source-bound reports intentionally fail verification when their Rust/Python source
manifest changes. Regenerate the full measurement grid using the README command,
run `tools/check_report.py`, then `tools/findings.py` and all tests. Preserve all
trials, failures and environment distinctions. Do not introduce a speed gate or
filter out unfavorable pairs. Formal measurement runs should execute alone.

`tools/mutation_check.py` compiles three deliberate protocol/scheduling faults and
requires behavioral assertion failures. It uses a project `.venv` and ignored
`results/local/` build/log directories. Those expected-failure logs are separate
from a normal release validation result.

`Dockerfile.validation` compiles the same source and Rust unit tests on Linux,
then runs the Python suites as a non-root user. For an existing Docker daemon:

```sh
docker build -f Dockerfile.validation -t tiny-fair-proxy-validation .
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=128m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 --pids-limit 128 tiny-fair-proxy-validation
```

Container/VM timing and memory are separate from native host results. Building
requires network access; execution uses loopback only. Do not change host DNS,
firewall, routing or Docker contexts for these tests. Keep personal settings,
credentials, state, toolchains and unsanitized local logs out of Git.
