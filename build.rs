use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, env, fs, path::Path, process::Command};

fn collect(path: &Path, files: &mut BTreeMap<String, String>) {
    if path.is_dir() {
        for entry in fs::read_dir(path).unwrap() {
            collect(&entry.unwrap().path(), files);
        }
    } else if path.extension().is_some_and(|e| e == "rs") {
        record(path, files);
    }
}
fn record(path: &Path, files: &mut BTreeMap<String, String>) {
    println!("cargo:rerun-if-changed={}", path.display());
    files.insert(
        path.to_str().unwrap().replace('\\', "/"),
        format!("{:x}", Sha256::digest(fs::read(path).unwrap())),
    );
}
fn main() {
    let mut files = BTreeMap::new();
    for name in ["Cargo.toml", "Cargo.lock", "build.rs"] {
        record(Path::new(name), &mut files);
    }
    collect(Path::new("src"), &mut files);
    let compiler = Command::new(env::var_os("RUSTC").unwrap())
        .arg("--version")
        .output()
        .unwrap();
    assert!(compiler.status.success());
    let identity = serde_json::json!({"schema_version":1,"files":files,"rustc":String::from_utf8(compiler.stdout).unwrap().trim(),"target":env::var("TARGET").unwrap(),"profile":env::var("PROFILE").unwrap()});
    fs::write(
        Path::new(&env::var_os("OUT_DIR").unwrap()).join("identity.json"),
        serde_json::to_vec(&identity).unwrap(),
    )
    .unwrap();
}
