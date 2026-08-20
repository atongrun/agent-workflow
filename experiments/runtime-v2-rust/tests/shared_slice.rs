use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("crate is under experiments/runtime-v2-rust")
        .to_path_buf()
}

fn temp_root(name: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock before unix epoch")
        .as_nanos();
    env::temp_dir().join(format!("rts022-rust-{name}-{}-{nanos}", std::process::id()))
}

#[test]
fn shared_slice_fixture_and_normal_path_pass() {
    let repo = repo_root();
    let state = temp_root("fixture");
    fs::create_dir_all(&state).expect("create state root");
    let exe = env!("CARGO_BIN_EXE_runtime-v2-rust");
    let output = Command::new(exe)
        .arg("verify")
        .arg("--fixture")
        .arg(repo.join("tests/fixtures/runtime_v2_shared_slice_cases.json"))
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--target")
        .arg(format!("test-{}", env::consts::OS))
        .output()
        .expect("run rust shared-slice verifier");
    assert!(
        output.status.success(),
        "verify failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("\"case_count\": 14"), "{stdout}");
    assert!(
        stdout.contains("\"python_invoked\": false"),
        "evidence must prove no Python child: {stdout}"
    );
    assert!(
        stdout.contains("\"startup_samples_ms\""),
        "evidence must include bounded startup samples: {stdout}"
    );
}
