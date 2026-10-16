# Third-party dependencies and license status

Original project code and documentation are licensed under the [MIT License](LICENSE).
Copyright (c) 2026 Andrew Yuan. This does not relicense third-party components
or determine repository visibility. The repository is now Public.

The locked Rust dependencies offer MIT terms, including those whose upstream
metadata uses legacy `MIT/Apache-2.0` notation. MIT is the selected option here.
`unicode-ident` additionally requires Unicode-3.0; its additional notice is
retained. Psutil is a development dependency under BSD-3-Clause. Original notices
and exact license texts from these installed, locked versions are preserved in
[THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt).

The checked dependency terms do not require changing the original project's MIT
license. Their attribution, permission/disclaimer and applicable non-endorsement
requirements still apply; preserve the relevant notices when redistributing
dependencies or binaries containing them. MIT for this project is not a claim
that all dependencies have been relicensed to MIT.

Runtime crates (exact transitive versions: Cargo.lock):

- serde / serde_json: MIT OR Apache-2.0.
- socket2: MIT OR Apache-2.0.
- libc: MIT OR Apache-2.0.
- signal-hook: MIT OR Apache-2.0; transitive dependency licenses are recorded in
  the [locked dependency list](docs/DEPENDENCIES.md). This includes unicode-ident
  with Unicode-3.0 terms, memchr (Unlicense OR MIT) and zmij (MIT).

Build-time source identity additionally uses sha2 (MIT OR Apache-2.0); exact
transitive versions and license expressions are in the locked dependency list.

Development: psutil 7.0.0 (BSD-3-Clause), Python (PSF and bundled notices), Rust
compiler/toolchain (its own upstream terms). No third-party source, toolchain or
binary is vendored in Git; only dependency license texts are included. Runtime or
container distributions must also retain the applicable Python, Rust and OS
component notices. Examples and measurements use synthetic byte streams,
not private network captures or external datasets.
