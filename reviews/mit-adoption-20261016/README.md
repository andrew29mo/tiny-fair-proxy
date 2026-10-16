# MIT adoption — 2026-10-16

Baseline: `7fe360973de79a0bd31806c69e58184269695c18`, initially clean.
The owner explicitly selected MIT. Original project code/documentation now use
the root `LICENSE`: Copyright (c) 2026 Andrew Yuan. Cargo declares `license = "MIT"`
and retains `publish = false`. GitHub remains Private with no new collaborators.
The earlier reviews' unselected-license observations remain historical, rather
than being rewritten as if MIT had already been selected.

## Dependency check

The locked Cargo metadata matches `docs/DEPENDENCIES.md`. All 27 locked external
Rust crates offer MIT terms. For alternative-license crates MIT is selected,
including the legacy slash notation used by signal-hook and version_check;
their installed distributions contain MIT license files. `unicode-ident` also
requires Unicode-3.0, which is preserved independently. Installed psutil 7.0.0
is a development dependency under BSD-3-Clause.

`THIRD_PARTY_LICENSES.txt` includes 29 exact upstream license-text entries:
27 Rust MIT texts, one additional Unicode text and the psutil BSD text. The
component/version, original filename and upstream/bundled-text SHA-256 inventory is in
`license-inventory.json`. Line endings are normalized to LF; terms and original
notices are otherwise retained, including their own
copyright dates; they are not replaced with the project's copyright. This is
consistent with MIT for original code while retaining dependency-specific terms.
No dependency source, runtime or executable is vendored. Bundled future binaries,
runtimes or containers still need their applicable third-party notices.

Primary reference terms: [MIT](https://opensource.org/license/mit),
[Unicode license](https://www.unicode.org/license.txt),
[psutil 7.0.0 BSD license](https://github.com/giampaolo/psutil/blob/release-7.0.0/LICENSE).
The bundled Unicode text comes from the locked crate, including its original
copyright year, rather than substituting the latest website text.

## Source-bound validation

No Rust implementation, Python behavior or tests are changed. Cargo license
metadata changes the compile-time source identity, so the native 24-trial grid,
JSON/HTML and generated README are refreshed, and both platform suites are rerun.
`receipt.json` binds the new metadata/source, executable/report hashes, native
and virtualized Linux observations and sanitized logs. Historical measurements
remain byte-for-byte intact in their labelled folders.

Native measurements run with Colima stopped and without concurrent heavy tests.
Linux is a separate non-root, read-only container correctness run, not native
Linux performance or VM RSS evidence. Each platform checks four Rust tests and
33 Python test methods. The owned container is removed and VM stopped afterwards.
The prior mutation evidence remains historical; it is not counted as a new run.
README retains workload, sampling and fairness limitations. Nothing in the
license change establishes a speedup, lower RSS or broader service guarantee.

Hosted CI remains separate from local evidence. Account billing restrictions
must not be reported as either executed tests or hosted success. File hygiene,
license text consistency and Private visibility are checked before/after upload.
