# Third-party dependencies and license status

No project open-source license has been selected by the owner. The private MVP
is not a grant to redistribute original project code. Dependencies retain their
own licenses; selecting the project's license is a separate future decision.

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
binary is vendored in Git. Examples and measurements use synthetic byte streams,
not private network captures or external datasets.
