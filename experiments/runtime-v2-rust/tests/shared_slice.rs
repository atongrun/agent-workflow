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

fn actual_target() -> &'static str {
    match (env::consts::OS, env::consts::ARCH) {
        ("linux", "x86_64") => "linux-x86_64",
        ("linux", "aarch64") => "linux-arm64",
        ("windows", "x86_64") => "windows-x86_64",
        ("macos", "x86_64") => "macos-x86_64",
        ("macos", "aarch64") => "macos-arm64",
        _ => "unknown",
    }
}

#[test]
fn shared_slice_fixture_and_normal_path_pass() {
    let repo = repo_root();
    let state = temp_root("fixture");
    fs::create_dir_all(&state).expect("create state root");
    let exe = env!("CARGO_BIN_EXE_runtime-v2-rust");
    let evidence = state.join("evidence").join("actual.json");
    let output = Command::new(exe)
        .current_dir(&repo)
        .arg("verify")
        .arg("--fixture")
        .arg(repo.join("tests/fixtures/runtime_v2_shared_slice_cases.json"))
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(".")
        .arg("--target")
        .arg(actual_target())
        .arg("--rustc-version")
        .arg("rustc test")
        .arg("--cargo-version")
        .arg("cargo test")
        .arg("--toolchain")
        .arg("1.85.1")
        .arg("--evidence")
        .arg(&evidence)
        .output()
        .expect("run rust shared-slice verifier");
    assert!(
        output.status.success(),
        "verify failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let evidence_text = fs::read_to_string(&evidence).expect("read evidence");
    assert!(evidence_text.contains("\"case_count\": 14"), "{evidence_text}");
    assert!(
        evidence_text.contains("\"python_invoked\": false"),
        "evidence must prove no Python child: {evidence_text}"
    );
    assert!(
        evidence_text.contains("\"active_writer_stop_denied\": true"),
        "evidence must prove active writer stop denial: {evidence_text}"
    );
    assert!(
        evidence_text.contains("\"status_git_readonly\": true"),
        "evidence must prove status Git read-only behavior: {evidence_text}"
    );
    assert!(
        evidence_text.contains("\"task_id\": \"runtime-v2-rts-022-rust-shared-slice\"")
            && evidence_text.contains("\"run_id\"")
            && evidence_text.contains("\"invocation_ids\"")
            && evidence_text.contains("\"decision_owner\""),
        "row evidence must carry stable identities and decision facts: {evidence_text}"
    );
    let aggregate_input = state.join("aggregate-input");
    fs::create_dir_all(&aggregate_input).expect("create aggregate input");
    for target in [
        "linux-x86_64",
        "linux-arm64",
        "windows-x86_64",
        "macos-x86_64",
        "macos-arm64",
    ] {
        let target_text = evidence_text
            .replace(
                &format!("\"target\": \"{}\"", actual_target()),
                &format!("\"target\": \"{target}\""),
            )
            .replace(
                &format!("\"actual_target\": \"{}\"", actual_target()),
                &format!("\"actual_target\": \"{target}\""),
            );
        fs::write(aggregate_input.join(format!("{target}.json")), target_text)
            .expect("write aggregate evidence");
    }
    let summary = state.join("summary.json");
    let aggregate = Command::new(exe)
        .arg("aggregate")
        .arg("--input")
        .arg(&aggregate_input)
        .arg("--fixture")
        .arg(repo.join("tests/fixtures/runtime_v2_shared_slice_cases.json"))
        .arg("--output")
        .arg(&summary)
        .output()
        .expect("run rust aggregate verifier");
    assert!(
        aggregate.status.success(),
        "aggregate failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&aggregate.stdout),
        String::from_utf8_lossy(&aggregate.stderr)
    );
    let summary = fs::read_to_string(summary).expect("read aggregate summary");
    assert!(
        summary.contains("RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE"),
        "aggregate summary must report eligibility gate: {summary}"
    );
    for (name, from, to) in [
        (
            "inject",
            "\"inject\": \"auth_prepared_only\"",
            "\"inject\": \"auth_prepared_only_drift\"",
        ),
        (
            "decision-source",
            "\"decision_source\": \"prepared_without_authorization:runtime-gate\"",
            "\"decision_source\": \"drift:runtime-gate\"",
        ),
        (
            "concrete-check",
            "\"assertion\": \"no_provider\"",
            "\"assertion\": \"no_provider_drift\"",
        ),
    ] {
        let mutated = evidence_text.replacen(from, to, 1);
        assert_ne!(mutated, evidence_text, "mutation source missing for {name}");
        let mutated_input = state.join(format!("aggregate-mutated-{name}"));
        fs::create_dir_all(&mutated_input).expect("create mutated aggregate input");
        for target in [
            "linux-x86_64",
            "linux-arm64",
            "windows-x86_64",
            "macos-x86_64",
            "macos-arm64",
        ] {
            let target_text = mutated
                .replace(
                    &format!("\"target\": \"{}\"", actual_target()),
                    &format!("\"target\": \"{target}\""),
                )
                .replace(
                    &format!("\"actual_target\": \"{}\"", actual_target()),
                    &format!("\"actual_target\": \"{target}\""),
                );
            fs::write(mutated_input.join(format!("{target}.json")), target_text)
                .expect("write mutated aggregate evidence");
        }
        let rejected = Command::new(exe)
            .arg("aggregate")
            .arg("--input")
            .arg(&mutated_input)
            .arg("--fixture")
            .arg(repo.join("tests/fixtures/runtime_v2_shared_slice_cases.json"))
            .arg("--output")
            .arg(state.join(format!("summary-mutated-{name}.json")))
            .output()
            .expect("run mutated Rust aggregate verifier");
        assert!(
            !rejected.status.success(),
            "aggregate must reject {name} drift\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&rejected.stdout),
            String::from_utf8_lossy(&rejected.stderr)
        );
    }
}

#[test]
fn fail_closed_journal_and_namespace_gates_are_enforced() {
    let repo = repo_root();
    let state = temp_root("fault-gates");
    fs::create_dir_all(&state).expect("create state root");
    let exe = env!("CARGO_BIN_EXE_runtime-v2-rust");

    let bad_run = Command::new(exe)
        .arg("status")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg("../escape")
        .output()
        .expect("run invalid run-id status");
    assert!(
        !bad_run.status.success(),
        "invalid run-id must fail closed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&bad_run.stdout),
        String::from_utf8_lossy(&bad_run.stderr)
    );

    let nonzero = "nonzero-result";
    let inject_nonzero = Command::new(exe)
        .arg("inject")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg(nonzero)
        .arg("--case")
        .arg("nonzero_result_with_valid_artifact")
        .output()
        .expect("inject nonzero result");
    assert!(
        inject_nonzero.status.success(),
        "nonzero inject failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&inject_nonzero.stdout),
        String::from_utf8_lossy(&inject_nonzero.stderr)
    );
    let nonzero_status = Command::new(exe)
        .arg("status")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg(nonzero)
        .output()
        .expect("status nonzero result");
    let nonzero_text = String::from_utf8_lossy(&nonzero_status.stdout);
    assert!(
        nonzero_status.status.success()
            && nonzero_text.contains("\"outcome\": \"HANDLER_FAILURE_NO_ACK\""),
        "nonzero durable result must not advance through a valid artifact: {nonzero_text}"
    );

    let missing_review = "review-missing";
    let inject_missing = Command::new(exe)
        .arg("inject")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg(missing_review)
        .arg("--case")
        .arg("review_missing_journal")
        .output()
        .expect("inject missing review journal");
    assert!(
        inject_missing.status.success(),
        "review missing inject failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&inject_missing.stdout),
        String::from_utf8_lossy(&inject_missing.stderr)
    );
    let review_status = Command::new(exe)
        .arg("status")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg(missing_review)
        .output()
        .expect("status missing review journal");
    let review_text = String::from_utf8_lossy(&review_status.stdout);
    assert!(
        review_status.status.success()
            && review_text.contains("\"outcome\": \"OWNER_DECISION_REQUIRED\""),
        "missing consumed review journal must require owner decision: {review_text}"
    );

    let extra = "extra-journal";
    let inject_extra = Command::new(exe)
        .arg("inject")
        .arg("--state")
        .arg(&state)
        .arg("--repo")
        .arg(&repo)
        .arg("--run-id")
        .arg(extra)
        .arg("--case")
        .arg("auth_authorized_prepared")
        .output()
        .expect("inject extra journal base");
    assert!(inject_extra.status.success(), "extra base inject failed");
    let invocations = state.join(extra).join("invocations");
    fs::write(invocations.join("extra.json"), "{}\n").expect("write extra journal identity");
    let inspect = Command::new(exe)
        .arg("inspect-journal-ids")
        .arg("--state")
        .arg(&state)
        .arg("--run-id")
        .arg(extra)
        .output()
        .expect("inspect exact journal ids");
    assert!(
        !inspect.status.success(),
        "extra journal identity must be rejected\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&inspect.stdout),
        String::from_utf8_lossy(&inspect.stderr)
    );
}

#[test]
fn static_writer_lock_and_status_readonly_boundaries_are_present() {
    let source = fs::read_to_string(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join("lib.rs"),
    )
    .expect("read rust source");
    assert!(
        source.contains(".create_new(true)"),
        "writer lock must use create_new identity"
    );
    assert!(
        source.contains("let _lock = WriterLock::acquire(&run_dir, run_id, \"run\")"),
        "run must hold the exact writer lock"
    );
    assert!(
        source.contains("let _lock = WriterLock::acquire(&run_dir, run_id, \"stop\")"),
        "stop must hold the exact writer lock"
    );
    let status_start = source
        .find("pub fn status_slice")
        .expect("status_slice function exists");
    let status_end = source[status_start..]
        .find("fn status_slice_inner")
        .expect("status_slice_inner follows status_slice")
        + status_start;
    assert!(
        !source[status_start..status_end].contains("WriterLock::acquire"),
        "status must not take a writer lock"
    );
    let revalidate_start = source
        .find("fn revalidate_trusted_repo")
        .expect("trusted repo revalidation exists");
    let revalidate_end = source[revalidate_start..]
        .find("fn revalidate_completed")
        .expect("completed revalidation follows trusted repo revalidation")
        + revalidate_start;
    assert!(
        !source[revalidate_start..revalidate_end].contains("configure_repo"),
        "trusted repo revalidation must be read-only"
    );
    assert!(
        source.contains("fn validate_successful_journal_result")
            && source.matches("validate_successful_journal_result(").count() >= 8,
        "successful-result journal joins must be enforced across run/status recovery"
    );
    let exact_start = source
        .find("fn exact_journal_ids")
        .expect("exact journal identity helper exists");
    let exact_end = source[exact_start..]
        .find("fn startup_samples")
        .expect("startup samples follows exact journal identities")
        + exact_start;
    assert!(
        source[exact_start..exact_end].contains("fs::read_dir")
            && !source[exact_start..exact_end].contains("read_envelope"),
        "exact_journal_ids must validate on-disk filename identities, not embedded journal fields"
    );
    assert!(
        source.contains("validate_run_id(run_id)?")
            && source.contains("repo_arg.canonicalize()"),
        "public run-id and --repo . cwd-drift gates must be static-visible"
    );
}
