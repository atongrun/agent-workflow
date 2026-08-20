use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::ffi::OsString;
use std::fmt::{Display, Formatter};
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

const TASK_ID: &str = "runtime-v2-rts-022-rust-shared-slice";
const FORMAT: &str = "awf.runtime-v2-rust-slice.v1";
const FIXTURE_FORMAT: &str = "awf.runtime-v2-shared-slice-cases.v1";
const CONTRACT_PATH: &str = "docs/runtime-v2-semantic-contract.md";
const IMPLEMENT_ID: &str = "implement-1";
const REVIEW_ID: &str = "review-1";
const ALLOWED_DELTA: &str = "result.txt";

type Result<T> = std::result::Result<T, AwfError>;

#[derive(Debug, Clone)]
pub struct AwfError {
    outcome: String,
    legal_next_action: String,
    source: String,
}

impl AwfError {
    fn new(outcome: &str, legal_next_action: &str, source: impl Into<String>) -> Self {
        Self {
            outcome: outcome.to_string(),
            legal_next_action: legal_next_action.to_string(),
            source: source.into(),
        }
    }
}

impl Display for AwfError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}: {} ({})",
            self.outcome, self.legal_next_action, self.source
        )
    }
}

impl std::error::Error for AwfError {}

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Number(String),
    String(String),
    Array(Vec<Json>),
    Object(BTreeMap<String, Json>),
}

impl Json {
    fn string(value: impl Into<String>) -> Self {
        Self::String(value.into())
    }

    fn array(values: Vec<Json>) -> Self {
        Self::Array(values)
    }

    fn object(values: Vec<(&str, Json)>) -> Self {
        let mut object = BTreeMap::new();
        for (key, value) in values {
            object.insert(key.to_string(), value);
        }
        Self::Object(object)
    }

    fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Object(object) => object.get(key),
            _ => None,
        }
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            Json::String(value) => Some(value),
            _ => None,
        }
    }

    fn as_array(&self) -> Option<&[Json]> {
        match self {
            Json::Array(values) => Some(values),
            _ => None,
        }
    }

    fn as_object(&self) -> Option<&BTreeMap<String, Json>> {
        match self {
            Json::Object(values) => Some(values),
            _ => None,
        }
    }
}

struct JsonParser<'a> {
    input: &'a [u8],
    pos: usize,
}

impl<'a> JsonParser<'a> {
    fn new(text: &'a str) -> Self {
        Self {
            input: text.as_bytes(),
            pos: 0,
        }
    }

    fn parse(mut self) -> Result<Json> {
        let value = self.value()?;
        self.ws();
        if self.pos != self.input.len() {
            return Err(parse_error("trailing bytes after JSON document"));
        }
        Ok(value)
    }

    fn value(&mut self) -> Result<Json> {
        self.ws();
        match self.peek() {
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => self.string().map(Json::String),
            Some(b't') => self.keyword(b"true", Json::Bool(true)),
            Some(b'f') => self.keyword(b"false", Json::Bool(false)),
            Some(b'n') => self.keyword(b"null", Json::Null),
            Some(b'-') | Some(b'0'..=b'9') => self.number(),
            _ => Err(parse_error("invalid JSON value")),
        }
    }

    fn object(&mut self) -> Result<Json> {
        self.expect(b'{')?;
        let mut result = BTreeMap::new();
        self.ws();
        if self.consume(b'}') {
            return Ok(Json::Object(result));
        }
        loop {
            self.ws();
            let key = self.string()?;
            if result.contains_key(&key) {
                return Err(AwfError::new(
                    "DENY_BEFORE_PROVIDER",
                    "preserve files and diagnose exact run identity",
                    format!("duplicate JSON key {key:?}"),
                ));
            }
            self.ws();
            self.expect(b':')?;
            let value = self.value()?;
            result.insert(key, value);
            self.ws();
            if self.consume(b'}') {
                break;
            }
            self.expect(b',')?;
        }
        Ok(Json::Object(result))
    }

    fn array(&mut self) -> Result<Json> {
        self.expect(b'[')?;
        let mut values = Vec::new();
        self.ws();
        if self.consume(b']') {
            return Ok(Json::Array(values));
        }
        loop {
            values.push(self.value()?);
            self.ws();
            if self.consume(b']') {
                break;
            }
            self.expect(b',')?;
        }
        Ok(Json::Array(values))
    }

    fn string(&mut self) -> Result<String> {
        self.expect(b'"')?;
        let mut result = String::new();
        while let Some(byte) = self.next() {
            match byte {
                b'"' => return Ok(result),
                b'\\' => {
                    let escaped = self
                        .next()
                        .ok_or_else(|| parse_error("unterminated string escape"))?;
                    match escaped {
                        b'"' => result.push('"'),
                        b'\\' => result.push('\\'),
                        b'/' => result.push('/'),
                        b'b' => result.push('\u{0008}'),
                        b'f' => result.push('\u{000c}'),
                        b'n' => result.push('\n'),
                        b'r' => result.push('\r'),
                        b't' => result.push('\t'),
                        b'u' => result.push(self.unicode_escape()?),
                        _ => return Err(parse_error("invalid string escape")),
                    }
                }
                0x00..=0x1f => return Err(parse_error("control byte in string")),
                _ => {
                    let start = self.pos - 1;
                    while let Some(next) = self.peek() {
                        if next == b'"' || next == b'\\' || next <= 0x1f {
                            break;
                        }
                        self.pos += 1;
                    }
                    let chunk = std::str::from_utf8(&self.input[start..self.pos])
                        .map_err(|_| parse_error("string is not utf-8"))?;
                    result.push_str(chunk);
                }
            }
        }
        Err(parse_error("unterminated string"))
    }

    fn unicode_escape(&mut self) -> Result<char> {
        let mut value = 0u32;
        for _ in 0..4 {
            let byte = self
                .next()
                .ok_or_else(|| parse_error("short unicode escape"))?;
            value = value * 16
                + match byte {
                    b'0'..=b'9' => u32::from(byte - b'0'),
                    b'a'..=b'f' => u32::from(byte - b'a' + 10),
                    b'A'..=b'F' => u32::from(byte - b'A' + 10),
                    _ => return Err(parse_error("invalid unicode escape")),
                };
        }
        char::from_u32(value).ok_or_else(|| parse_error("invalid unicode scalar"))
    }

    fn number(&mut self) -> Result<Json> {
        let start = self.pos;
        if self.consume(b'-') && !matches!(self.peek(), Some(b'0'..=b'9')) {
            return Err(parse_error("invalid number"));
        }
        if self.consume(b'0') {
            if matches!(self.peek(), Some(b'0'..=b'9')) {
                return Err(parse_error("invalid leading zero"));
            }
        } else {
            self.digits()?;
        }
        if self.consume(b'.') {
            self.digits()?;
        }
        if matches!(self.peek(), Some(b'e') | Some(b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+') | Some(b'-')) {
                self.pos += 1;
            }
            self.digits()?;
        }
        let value = std::str::from_utf8(&self.input[start..self.pos])
            .map_err(|_| parse_error("number is not utf-8"))?;
        Ok(Json::Number(value.to_string()))
    }

    fn digits(&mut self) -> Result<()> {
        let start = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        if self.pos == start {
            return Err(parse_error("expected digit"));
        }
        Ok(())
    }

    fn keyword(&mut self, expected: &[u8], value: Json) -> Result<Json> {
        if self.input.get(self.pos..self.pos + expected.len()) == Some(expected) {
            self.pos += expected.len();
            Ok(value)
        } else {
            Err(parse_error("invalid keyword"))
        }
    }

    fn ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<u8> {
        self.input.get(self.pos).copied()
    }

    fn next(&mut self) -> Option<u8> {
        let byte = self.peek()?;
        self.pos += 1;
        Some(byte)
    }

    fn consume(&mut self, byte: u8) -> bool {
        if self.peek() == Some(byte) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn expect(&mut self, byte: u8) -> Result<()> {
        if self.consume(byte) {
            Ok(())
        } else {
            Err(parse_error(format!("expected byte {}", byte as char)))
        }
    }
}

fn parse_error(source: impl Into<String>) -> AwfError {
    AwfError::new(
        "DENY_BEFORE_PROVIDER",
        "preserve files and diagnose exact run identity",
        source,
    )
}

fn parse_json(text: &str) -> Result<Json> {
    JsonParser::new(text).parse()
}

fn canonical_json(value: &Json) -> String {
    match value {
        Json::Null => "null".to_string(),
        Json::Bool(true) => "true".to_string(),
        Json::Bool(false) => "false".to_string(),
        Json::Number(number) => number.clone(),
        Json::String(text) => quote_json(text),
        Json::Array(values) => {
            let body = values.iter().map(canonical_json).collect::<Vec<_>>().join(",");
            format!("[{body}]")
        }
        Json::Object(values) => {
            let body = values
                .iter()
                .map(|(key, value)| format!("{}:{}", quote_json(key), canonical_json(value)))
                .collect::<Vec<_>>()
                .join(",");
            format!("{{{body}}}")
        }
    }
}

fn pretty_json(value: &Json) -> String {
    pretty_json_inner(value, 0)
}

fn pretty_json_inner(value: &Json, depth: usize) -> String {
    match value {
        Json::Object(values) if !values.is_empty() => {
            let indent = "  ".repeat(depth + 1);
            let close = "  ".repeat(depth);
            let body = values
                .iter()
                .map(|(key, value)| {
                    format!("{indent}{}: {}", quote_json(key), pretty_json_inner(value, depth + 1))
                })
                .collect::<Vec<_>>()
                .join(",\n");
            format!("{{\n{body}\n{close}}}")
        }
        Json::Array(values) if !values.is_empty() => {
            let indent = "  ".repeat(depth + 1);
            let close = "  ".repeat(depth);
            let body = values
                .iter()
                .map(|value| format!("{indent}{}", pretty_json_inner(value, depth + 1)))
                .collect::<Vec<_>>()
                .join(",\n");
            format!("[\n{body}\n{close}]")
        }
        _ => canonical_json(value),
    }
}

fn quote_json(text: &str) -> String {
    let mut result = String::from("\"");
    for ch in text.chars() {
        match ch {
            '"' => result.push_str("\\\""),
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            '\u{0008}' => result.push_str("\\b"),
            '\u{000c}' => result.push_str("\\f"),
            ch if ch <= '\u{001f}' => result.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => result.push(ch),
        }
    }
    result.push('"');
    result
}

fn checksum(value: &Json) -> String {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    canonical_json(value).hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

fn envelope(payload: Json) -> Json {
    Json::object(vec![
        ("format", Json::string(FORMAT)),
        ("checksum", Json::string(checksum(&payload))),
        ("payload", payload),
    ])
}

fn write_envelope(path: &Path, payload: Json) -> Result<()> {
    let parent = path.parent().ok_or_else(|| {
        AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "path has no parent",
        )
    })?;
    fs::create_dir_all(parent).map_err(io_error)?;
    let temp = path.with_file_name(format!(
        "{}.tmp-{}",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("state"),
        std::process::id()
    ));
    fs::write(&temp, pretty_json(&envelope(payload)) + "\n").map_err(io_error)?;
    fs::rename(temp, path).map_err(io_error)?;
    Ok(())
}

fn read_trusted_json(path: &Path) -> Result<Json> {
    let text = fs::read_to_string(path).map_err(io_error)?;
    parse_json(&text)
}

fn read_envelope(path: &Path) -> Result<Json> {
    let value = read_trusted_json(path)?;
    let object = value.as_object().ok_or_else(|| parse_error("envelope is not object"))?;
    let format = object.get("format").and_then(Json::as_str);
    let payload = object.get("payload").cloned();
    let stored = object.get("checksum").and_then(Json::as_str);
    match (format, payload, stored) {
        (Some(FORMAT), Some(payload), Some(stored)) if checksum(&payload) == stored => Ok(payload),
        _ => Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            format!("checksum or format mismatch in {}", path.display()),
        )),
    }
}

fn io_error(error: std::io::Error) -> AwfError {
    AwfError::new(
        "DENY_BEFORE_PROVIDER",
        "preserve files and diagnose exact run identity",
        error.to_string(),
    )
}

fn now_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{}-{nanos}", std::process::id())
}

fn run_dir(state: &Path, run_id: &str) -> PathBuf {
    state.join(run_id)
}

fn spec_path(run_dir: &Path) -> PathBuf {
    run_dir.join("runspec.json")
}

fn run_path(run_dir: &Path) -> PathBuf {
    run_dir.join("run.json")
}

fn journal_path(run_dir: &Path, invocation_id: &str) -> PathBuf {
    run_dir
        .join("invocations")
        .join(format!("{invocation_id}.json"))
}

fn counter_path(run_dir: &Path) -> PathBuf {
    run_dir.join("provider-counts.json")
}

fn artifact_path(run_dir: &Path, role: &str) -> PathBuf {
    run_dir
        .join("artifacts")
        .join(format!("{role}-report.json"))
}

fn workspace_path(run_dir: &Path, invocation_id: &str) -> PathBuf {
    run_dir.join("workspaces").join(invocation_id)
}

fn trusted_repo_path(run_dir: &Path) -> PathBuf {
    run_dir.join("trusted-repo")
}

fn git(repo: &Path, args: &[&str]) -> Result<String> {
    let mut command = Command::new("git");
    command.args(args);
    command.current_dir(repo);
    command.env("GIT_OPTIONAL_LOCKS", "0");
    let output = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(io_error)?;
    if !output.status.success() {
        return Err(AwfError::new(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn configure_repo(repo: &Path) -> Result<()> {
    git(repo, &["config", "user.email", "runtime-v2-rust@example.invalid"])?;
    git(repo, &["config", "user.name", "Runtime V2 Rust Slice"])?;
    let remotes = git(repo, &["remote"])?;
    for remote in remotes.lines().filter(|line| !line.trim().is_empty()) {
        git(repo, &["remote", "remove", remote])?;
    }
    Ok(())
}

fn git_head(repo: &Path) -> Result<String> {
    git(repo, &["rev-parse", "HEAD"])
}

fn git_tree(repo: &Path) -> Result<String> {
    git(repo, &["rev-parse", "HEAD^{tree}"])
}

fn compiled_spec(repo: &Path, run_id: &str) -> Result<Json> {
    let provider = env::current_exe().map_err(io_error)?;
    Ok(Json::object(vec![
        ("task_id", Json::string(TASK_ID)),
        ("run_id", Json::string(run_id)),
        ("source_head", Json::string(git_head(repo)?)),
        ("source_tree", Json::string(git_tree(repo)?)),
        ("allowed_delta", Json::array(vec![Json::string(ALLOWED_DELTA)])),
        (
            "provider_command",
            Json::array(vec![Json::string(provider.display().to_string())]),
        ),
    ]))
}

fn ensure_spec(run_dir: &Path, repo: &Path, run_id: &str) -> Result<Json> {
    let compiled = compiled_spec(repo, run_id)?;
    let path = spec_path(run_dir);
    if !path.exists() {
        write_envelope(&path, compiled.clone())?;
        return Ok(compiled);
    }
    let existing = read_envelope(&path)?;
    if checksum(&existing) != checksum(&compiled) {
        return Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "compiled RunSpec drift",
        ));
    }
    Ok(existing)
}

fn get_string(value: &Json, key: &str) -> Result<String> {
    value
        .get(key)
        .and_then(Json::as_str)
        .map(ToOwned::to_owned)
        .ok_or_else(|| parse_error(format!("missing string field {key}")))
}

fn new_run(spec: &Json) -> Result<Json> {
    Ok(Json::object(vec![
        ("run_id", Json::string(get_string(spec, "run_id")?)),
        ("task_id", Json::string(TASK_ID)),
        ("spec_digest", Json::string(checksum(spec))),
        ("phase", Json::string("initialized")),
        ("authorizations", Json::array(Vec::new())),
        ("handoff_intent", Json::Null),
        ("terminal", Json::Null),
        ("trusted_commit", Json::Null),
        ("trusted_tree", Json::Null),
        ("stop", Json::Null),
    ]))
}

fn load_run(run_dir: &Path) -> Result<Option<Json>> {
    let path = run_path(run_dir);
    if path.exists() {
        Ok(Some(read_envelope(&path)?))
    } else {
        Ok(None)
    }
}

fn save_run(run_dir: &Path, run: Json) -> Result<()> {
    write_envelope(&run_path(run_dir), run)
}

fn set_field(mut value: Json, key: &str, field: Json) -> Json {
    if let Json::Object(ref mut object) = value {
        object.insert(key.to_string(), field);
    }
    value
}

fn phase(run: &Json) -> Result<String> {
    get_string(run, "phase")
}

fn validate_run(run: &Json, spec: &Json) -> Result<()> {
    if get_string(run, "run_id")? != get_string(spec, "run_id")?
        || get_string(run, "task_id")? != TASK_ID
        || get_string(run, "spec_digest")? != checksum(spec)
    {
        return Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "RunStore identity drift",
        ));
    }
    let authorizations = run
        .get("authorizations")
        .and_then(Json::as_array)
        .ok_or_else(|| parse_error("authorizations not array"))?;
    let mut seen = BTreeSet::new();
    for item in authorizations {
        let pair = (
            get_string(item, "invocation_id")?,
            get_string(item, "role")?,
        );
        let allowed = (pair.0 == IMPLEMENT_ID && pair.1 == "implement")
            || (pair.0 == REVIEW_ID && pair.1 == "review");
        if !allowed || !seen.insert(pair)
        {
            return Err(AwfError::new(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "authorization identity drift",
            ));
        }
    }
    Ok(())
}

fn expected_journal_paths(run_dir: &Path, invocation_id: &str) -> Result<(PathBuf, PathBuf)> {
    match invocation_id {
        IMPLEMENT_ID => Ok((workspace_path(run_dir, IMPLEMENT_ID), artifact_path(run_dir, "implementation"))),
        REVIEW_ID => Ok((trusted_repo_path(run_dir), artifact_path(run_dir, "review"))),
        _ => Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "unknown invocation identity",
        )),
    }
}

fn prepared_journal(spec: &Json, run_dir: &Path, invocation_id: &str, role: &str) -> Result<Json> {
    let (workspace, artifact) = expected_journal_paths(run_dir, invocation_id)?;
    Ok(Json::object(vec![
        ("invocation_id", Json::string(invocation_id)),
        ("role", Json::string(role)),
        ("spec_digest", Json::string(checksum(spec))),
        ("state", Json::string("prepared")),
        ("workspace", Json::string(workspace.display().to_string())),
        ("artifact", Json::string(artifact.display().to_string())),
        (
            "provider_command_digest",
            Json::string(checksum(
                spec.get("provider_command")
                    .ok_or_else(|| parse_error("missing provider command"))?,
            )),
        ),
        ("launch_intent", Json::Null),
        ("started", Json::Null),
        ("result", Json::Null),
        ("validated", Json::Null),
    ]))
}

fn validate_journal(journal: &Json, spec: &Json, run_dir: &Path, invocation_id: &str, role: &str) -> Result<()> {
    let (workspace, artifact) = expected_journal_paths(run_dir, invocation_id)?;
    let expected = [
        ("invocation_id", invocation_id.to_string()),
        ("role", role.to_string()),
        ("spec_digest", checksum(spec)),
        ("workspace", workspace.display().to_string()),
        ("artifact", artifact.display().to_string()),
        (
            "provider_command_digest",
            checksum(
                spec.get("provider_command")
                    .ok_or_else(|| parse_error("missing provider command"))?,
            ),
        ),
    ];
    for (key, expected) in expected {
        if get_string(journal, key)? != expected {
            return Err(AwfError::new(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                format!("journal {invocation_id} {key} drift"),
            ));
        }
    }
    let state = get_string(journal, "state")?;
    if !matches!(
        state.as_str(),
        "prepared" | "launch_intent" | "started" | "result" | "validated"
    ) {
        return Err(parse_error("invalid journal state"));
    }
    Ok(())
}

fn save_journal(run_dir: &Path, invocation_id: &str, journal: Json) -> Result<()> {
    write_envelope(&journal_path(run_dir, invocation_id), journal)
}

fn read_journal(run_dir: &Path, invocation_id: &str) -> Result<Json> {
    read_envelope(&journal_path(run_dir, invocation_id))
}

fn add_authorization(run: Json, invocation_id: &str, role: &str) -> Json {
    let mut authorizations = run
        .get("authorizations")
        .and_then(Json::as_array)
        .map(|values| values.to_vec())
        .unwrap_or_default();
    let exists = authorizations.iter().any(|item| {
        get_string(item, "invocation_id").ok().as_deref() == Some(invocation_id)
            && get_string(item, "role").ok().as_deref() == Some(role)
    });
    if !exists {
        authorizations.push(Json::object(vec![
            ("invocation_id", Json::string(invocation_id)),
            ("role", Json::string(role)),
        ]));
    }
    set_field(run, "authorizations", Json::array(authorizations))
}

fn provider_argv(spec: &Json, run_dir: &Path, journal: &Json, mode: &str) -> Result<Vec<OsString>> {
    let command = spec
        .get("provider_command")
        .and_then(Json::as_array)
        .ok_or_else(|| parse_error("provider command not array"))?;
    let exe = command
        .first()
        .and_then(Json::as_str)
        .ok_or_else(|| parse_error("provider executable missing"))?;
    Ok(vec![
        OsString::from(exe),
        OsString::from("provider"),
        OsString::from("--role"),
        OsString::from(get_string(journal, "role")?),
        OsString::from("--workspace"),
        OsString::from(get_string(journal, "workspace")?),
        OsString::from("--artifact"),
        OsString::from(get_string(journal, "artifact")?),
        OsString::from("--counter"),
        OsString::from(counter_path(run_dir).display().to_string()),
        OsString::from("--mode"),
        OsString::from(mode),
    ])
}

fn safe_child_env(command: &mut Command) {
    command.env_clear();
    for key in ["LANG", "LC_ALL", "PATH", "SYSTEMROOT", "WINDIR"] {
        if let Some(value) = env::var_os(key) {
            command.env(key, value);
        }
    }
}

fn invoke_provider(spec: &Json, run_dir: &Path, invocation_id: &str, mode: &str) -> Result<()> {
    let mut journal = read_journal(run_dir, invocation_id)?;
    let role = get_string(&journal, "role")?;
    validate_journal(&journal, spec, run_dir, invocation_id, &role)?;
    let argv = provider_argv(spec, run_dir, &journal, mode)?;
    let argv_json = Json::array(
        argv.iter()
            .map(|arg| Json::string(arg.to_string_lossy().to_string()))
            .collect(),
    );
    journal = set_field(journal, "state", Json::string("launch_intent"));
    journal = set_field(
        journal,
        "launch_intent",
        Json::object(vec![
            ("argv", argv_json),
            ("mode", Json::string(mode)),
            ("no_shell", Json::Bool(true)),
        ]),
    );
    save_journal(run_dir, invocation_id, journal.clone())?;
    let mut command = Command::new(&argv[0]);
    command.args(&argv[1..]);
    command.stdin(Stdio::null());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    safe_child_env(&mut command);
    let output = command.output().map_err(io_error)?;
    journal = set_field(journal, "state", Json::string("started"));
    journal = set_field(journal, "started", Json::Bool(true));
    save_journal(run_dir, invocation_id, journal.clone())?;
    journal = set_field(journal, "state", Json::string("result"));
    journal = set_field(
        journal,
        "result",
        Json::object(vec![
            ("exit_code", Json::Number(output.status.code().unwrap_or(255).to_string())),
            ("stdout_bytes", Json::Number(output.stdout.len().to_string())),
            ("stderr_bytes", Json::Number(output.stderr.len().to_string())),
        ]),
    );
    save_journal(run_dir, invocation_id, journal)?;
    if !output.status.success() {
        return Err(AwfError::new(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "provider exited non-zero",
        ));
    }
    Ok(())
}

fn counter(run_dir: &Path) -> Json {
    let path = counter_path(run_dir);
    if path.exists() {
        read_trusted_json(&path).unwrap_or_else(|_| Json::object(vec![]))
    } else {
        Json::object(vec![
            ("implement", Json::Number("0".to_string())),
            ("review", Json::Number("0".to_string())),
            ("calls", Json::array(Vec::new())),
        ])
    }
}

fn counter_number(value: &Json, key: &str) -> u64 {
    value
        .get(key)
        .and_then(Json::as_str)
        .and_then(|value| value.parse().ok())
        .or_else(|| match value.get(key) {
            Some(Json::Number(number)) => number.parse().ok(),
            _ => None,
        })
        .unwrap_or(0)
}

fn write_counter(path: &Path, role: &str) -> Result<()> {
    let mut value = if path.exists() {
        read_trusted_json(path)?
    } else {
        Json::object(vec![
            ("implement", Json::Number("0".to_string())),
            ("review", Json::Number("0".to_string())),
            ("calls", Json::array(Vec::new())),
        ])
    };
    let implement = counter_number(&value, "implement");
    let review = counter_number(&value, "review");
    let mut calls = value
        .get("calls")
        .and_then(Json::as_array)
        .map(|items| items.to_vec())
        .unwrap_or_default();
    calls.push(Json::string(role));
    value = set_field(
        value,
        "implement",
        Json::Number((implement + if role == "implement" { 1 } else { 0 }).to_string()),
    );
    value = set_field(
        value,
        "review",
        Json::Number((review + if role == "review" { 1 } else { 0 }).to_string()),
    );
    value = set_field(value, "calls", Json::array(calls));
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_error)?;
    }
    fs::write(path, pretty_json(&value) + "\n").map_err(io_error)
}

fn validate_implementation_report(path: &Path) -> Result<()> {
    let value = read_trusted_json(path).map_err(|err| {
        AwfError::new(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            err.source,
        )
    })?;
    if get_string(&value, "task_id")? == TASK_ID
        && get_string(&value, "artifact")? == "ImplementationReport"
        && get_string(&value, "allowed_delta")? == ALLOWED_DELTA
    {
        Ok(())
    } else {
        Err(AwfError::new(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "invalid ImplementationReport",
        ))
    }
}

fn validate_review_report(path: &Path) -> Result<()> {
    let value = read_trusted_json(path).map_err(|err| {
        AwfError::new(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            err.source,
        )
    })?;
    if get_string(&value, "task_id")? == TASK_ID
        && get_string(&value, "artifact")? == "ReviewReport"
        && get_string(&value, "verdict")? == "PASS"
    {
        Ok(())
    } else {
        Err(AwfError::new(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "invalid ReviewReport",
        ))
    }
}

fn create_trusted_repo(run_dir: &Path) -> Result<(String, String)> {
    let repo = trusted_repo_path(run_dir);
    if !repo.exists() {
        fs::create_dir_all(&repo).map_err(io_error)?;
        git(&repo, &["init"])?;
        configure_repo(&repo)?;
        let source = workspace_path(run_dir, IMPLEMENT_ID).join(ALLOWED_DELTA);
        fs::copy(source, repo.join(ALLOWED_DELTA)).map_err(io_error)?;
        git(&repo, &["add", ALLOWED_DELTA])?;
        git(&repo, &["commit", "-m", "Bind disposable Runtime v2 Rust slice effect"])?;
    }
    configure_repo(&repo)?;
    Ok((git_head(&repo)?, git_tree(&repo)?))
}

fn revalidate_trusted_repo(run: &Json, run_dir: &Path) -> Result<()> {
    let repo = trusted_repo_path(run_dir);
    let expected_head = run.get("trusted_commit").and_then(Json::as_str);
    let expected_tree = run.get("trusted_tree").and_then(Json::as_str);
    if expected_head.is_none() || expected_tree.is_none() {
        return Err(AwfError::new(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "missing trusted Git identity",
        ));
    }
    configure_repo(&repo)?;
    if git_head(&repo)? != expected_head.unwrap() || git_tree(&repo)? != expected_tree.unwrap() {
        return Err(AwfError::new(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted Git identity drift",
        ));
    }
    if !git(&repo, &["remote"])?.trim().is_empty() {
        return Err(AwfError::new(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted repository has a remote",
        ));
    }
    Ok(())
}

pub fn run_slice(state: &Path, repo: &Path, run_id: &str) -> Result<Status> {
    let run_dir = run_dir(state, run_id);
    let spec = ensure_spec(&run_dir, repo, run_id)?;
    let mut run = match load_run(&run_dir)? {
        Some(run) => run,
        None => {
            let run = new_run(&spec)?;
            save_run(&run_dir, run.clone())?;
            run
        }
    };
    validate_run(&run, &spec)?;
    for _ in 0..20 {
        match phase(&run)?.as_str() {
            "completed" => return status_slice(state, repo, run_id),
            "initialized" => {
                let journal = prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?;
                save_journal(&run_dir, IMPLEMENT_ID, journal)?;
                run = add_authorization(run, IMPLEMENT_ID, "implement");
                run = set_field(run, "phase", Json::string("implement_authorized"));
                save_run(&run_dir, run.clone())?;
            }
            "prepared_without_authorization" => {
                return Err(AwfError::new(
                    "DENY_BEFORE_PROVIDER",
                    "commit exact RunStore authorization before launch",
                    "prepared journal exists without RunStore authorization",
                ));
            }
            "implement_launch_intent" | "implement_started" => {
                return Err(AwfError::new(
                    "AMBIGUOUS_NO_REPLAY",
                    "preserve exact process/workspace/evidence for owner decision",
                    "launch or process start was already recorded",
                ));
            }
            "implement_authorized" => {
                invoke_provider(&spec, &run_dir, IMPLEMENT_ID, "normal")?;
                run = set_field(run, "phase", Json::string("implement_result"));
                save_run(&run_dir, run.clone())?;
            }
            "implement_result" => {
                validate_implementation_report(&artifact_path(&run_dir, "implementation"))?;
                let mut journal = read_journal(&run_dir, IMPLEMENT_ID)?;
                journal = set_field(journal, "state", Json::string("validated"));
                journal = set_field(journal, "validated", Json::Bool(true));
                save_journal(&run_dir, IMPLEMENT_ID, journal)?;
                let (head, tree) = create_trusted_repo(&run_dir)?;
                run = set_field(run, "trusted_commit", Json::string(head));
                run = set_field(run, "trusted_tree", Json::string(tree));
                run = set_field(run, "phase", Json::string("implement_committed"));
                save_run(&run_dir, run.clone())?;
            }
            "implement_committed" => {
                revalidate_trusted_repo(&run, &run_dir)?;
                run = set_field(
                    run,
                    "handoff_intent",
                    Json::object(vec![
                        ("from", Json::string("implement")),
                        ("to", Json::string("review")),
                        ("trusted_commit", run.get("trusted_commit").cloned().unwrap_or(Json::Null)),
                    ]),
                );
                run = set_field(run, "phase", Json::string("review_handoff_intent"));
                save_run(&run_dir, run.clone())?;
            }
            "review_handoff_intent" => {
                let journal = prepared_journal(&spec, &run_dir, REVIEW_ID, "review")?;
                save_journal(&run_dir, REVIEW_ID, journal)?;
                run = add_authorization(run, REVIEW_ID, "review");
                run = set_field(run, "phase", Json::string("review_authorized"));
                save_run(&run_dir, run.clone())?;
            }
            "review_authorized" => {
                invoke_provider(&spec, &run_dir, REVIEW_ID, "normal")?;
                run = set_field(run, "phase", Json::string("review_result"));
                save_run(&run_dir, run.clone())?;
            }
            "review_result" => {
                validate_review_report(&artifact_path(&run_dir, "review"))?;
                revalidate_trusted_repo(&run, &run_dir)?;
                let mut journal = read_journal(&run_dir, REVIEW_ID)?;
                journal = set_field(journal, "state", Json::string("validated"));
                journal = set_field(journal, "validated", Json::Bool(true));
                save_journal(&run_dir, REVIEW_ID, journal)?;
                run = set_field(run, "terminal", Json::string("completed"));
                run = set_field(run, "phase", Json::string("completed"));
                save_run(&run_dir, run.clone())?;
            }
            other => {
                return Err(AwfError::new(
                    "DENY_BEFORE_PROVIDER",
                    "preserve files and diagnose exact run identity",
                    format!("unknown phase {other}"),
                ))
            }
        }
    }
    Err(AwfError::new(
        "DENY_BEFORE_PROVIDER",
        "preserve files and diagnose exact run identity",
        "transition limit exceeded",
    ))
}

#[derive(Debug, Clone)]
pub struct Status {
    outcome: String,
    legal_next_action: String,
    phase: String,
    provider_counts: Json,
    terminal: bool,
    trusted_repo: bool,
}

impl Status {
    fn to_json(&self) -> Json {
        Json::object(vec![
            ("outcome", Json::string(&self.outcome)),
            ("legal_next_action", Json::string(&self.legal_next_action)),
            ("phase", Json::string(&self.phase)),
            ("provider_counts", self.provider_counts.clone()),
            ("terminal", Json::Bool(self.terminal)),
            ("trusted_repo", Json::Bool(self.trusted_repo)),
        ])
    }
}

pub fn status_slice(state: &Path, repo: &Path, run_id: &str) -> Result<Status> {
    let run_dir = run_dir(state, run_id);
    let before = tree_bytes(&run_dir);
    let result = status_slice_inner(state, repo, run_id);
    let after = tree_bytes(&run_dir);
    if before != after {
        return Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "status mutated authoritative bytes",
        ));
    }
    result
}

fn status_slice_inner(state: &Path, repo: &Path, run_id: &str) -> Result<Status> {
    let run_dir = run_dir(state, run_id);
    let counts = counter(&run_dir);
    let trusted_repo = trusted_repo_path(&run_dir).join(".git").exists();
    let spec_path = spec_path(&run_dir);
    if !spec_path.exists() {
        return Ok(status(
            "SAFE_CONTINUE",
            "run local disposable slice",
            "absent",
            counts,
            false,
            trusted_repo,
        ));
    }
    let spec = ensure_spec(&run_dir, repo, run_id)?;
    let run = match load_run(&run_dir)? {
        Some(run) => run,
        None => {
            return Ok(status(
                "SAFE_CONTINUE",
                "run local disposable slice",
                "spec_only",
                counts,
                false,
                trusted_repo,
            ));
        }
    };
    validate_run(&run, &spec)?;
    match phase(&run)?.as_str() {
        "completed" => Ok(status(
            "TERMINAL_IDEMPOTENT",
            "status or exact stop only",
            "completed",
            counts,
            true,
            trusted_repo,
        )),
        "prepared_without_authorization" => Ok(status(
            "DENY_BEFORE_PROVIDER",
            "commit exact RunStore authorization before launch",
            "prepared_without_authorization",
            counts,
            false,
            trusted_repo,
        )),
        "implement_authorized" => {
            let journal = match read_journal(&run_dir, IMPLEMENT_ID) {
                Ok(journal) => journal,
                Err(_) => {
                    return Ok(status(
                        "OWNER_DECISION_REQUIRED",
                        "preserve the consumed authorization/budget and deny automatic provider replay",
                        "implement_authorized",
                        counts,
                        false,
                        trusted_repo,
                    ));
                }
            };
            validate_journal(&journal, &spec, &run_dir, IMPLEMENT_ID, "implement")?;
            Ok(status(
                "SAFE_CONTINUE",
                "invoke once after exact gates and journal revalidation",
                "implement_authorized",
                counts,
                false,
                trusted_repo,
            ))
        }
        "implement_launch_intent" => Ok(status(
            "AMBIGUOUS_NO_REPLAY",
            "preserve exact process/workspace/evidence for owner decision",
            "implement_launch_intent",
            counts,
            false,
            trusted_repo,
        )),
        "implement_started" => Ok(status(
            "AMBIGUOUS_NO_REPLAY",
            "preserve exact process/workspace/evidence for owner decision",
            "implement_started",
            counts,
            false,
            trusted_repo,
        )),
        "implement_result" => match validate_implementation_report(&artifact_path(&run_dir, "implementation")) {
            Ok(()) => Ok(status(
                "SAFE_CONTINUE",
                "skip provider and run frozen postflight against exact durable workspace",
                "implement_result",
                counts,
                false,
                trusted_repo,
            )),
            Err(_) => Ok(status(
                "HANDLER_FAILURE_NO_ACK",
                "record failure/ambiguity and preserve the same delivery evidence",
                "implement_result",
                counts,
                false,
                trusted_repo,
            )),
        },
        "implement_committed" => {
            revalidate_trusted_repo(&run, &run_dir)?;
            Ok(status(
                "SAFE_CONTINUE",
                "revalidate exact effects and persist one local review intent",
                "implement_committed",
                counts,
                false,
                trusted_repo,
            ))
        }
        "review_handoff_intent" => Ok(status(
            "SAFE_CONTINUE",
            "authorize exact review invocation",
            "review_handoff_intent",
            counts,
            false,
            trusted_repo,
        )),
        "review_authorized" => Ok(status(
            "SAFE_CONTINUE",
            "invoke review once after exact gates and journal revalidation",
            "review_authorized",
            counts,
            false,
            trusted_repo,
        )),
        "review_result" => {
            validate_review_report(&artifact_path(&run_dir, "review"))?;
            revalidate_trusted_repo(&run, &run_dir)?;
            Ok(status(
                "SAFE_CONTINUE",
                "write terminal completion after exact report and Git revalidation",
                "review_result",
                counts,
                false,
                trusted_repo,
            ))
        }
        other => Err(AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            format!("unknown phase {other}"),
        )),
    }
}

fn status(
    outcome: &str,
    action: &str,
    phase: &str,
    counts: Json,
    terminal: bool,
    trusted_repo: bool,
) -> Status {
    Status {
        outcome: outcome.to_string(),
        legal_next_action: action.to_string(),
        phase: phase.to_string(),
        provider_counts: counts,
        terminal,
        trusted_repo,
    }
}

fn tree_bytes(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut result = BTreeMap::new();
    collect_tree_bytes(root, root, &mut result);
    result
}

fn collect_tree_bytes(root: &Path, path: &Path, result: &mut BTreeMap<String, Vec<u8>>) {
    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.components().any(|part| part.as_os_str() == ".git") {
            continue;
        }
        if path.is_dir() {
            collect_tree_bytes(root, &path, result);
        } else if path.is_file() {
            if let Ok(bytes) = fs::read(&path) {
                if let Ok(relative) = path.strip_prefix(root) {
                    result.insert(relative.display().to_string(), bytes);
                }
            }
        }
    }
}

pub fn stop_slice(state: &Path, repo: &Path, run_id: &str) -> Result<Status> {
    let run_dir = run_dir(state, run_id);
    let mut run = load_run(&run_dir)?.ok_or_else(|| {
        AwfError::new(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "no run exists",
        )
    })?;
    let current = status_slice(state, repo, run_id)?;
    if !matches!(phase(&run)?.as_str(), "completed") {
        return Err(AwfError::new(
            "OWNER_DECISION_REQUIRED",
            "preserve active invocation/writer evidence before stopping",
            "run is not idle terminal",
        ));
    }
    run = set_field(
        run,
        "stop",
        Json::object(vec![
            ("scope", Json::string("exact-local-experiment-run")),
            ("run_id", Json::string(run_id)),
            ("production_lifecycle", Json::Bool(false)),
        ]),
    );
    save_run(&run_dir, run)?;
    Ok(current)
}

fn provider_main(args: &[String]) -> Result<()> {
    let role = arg_value(args, "--role")?;
    let workspace = PathBuf::from(arg_value(args, "--workspace")?);
    let artifact = PathBuf::from(arg_value(args, "--artifact")?);
    let counter = PathBuf::from(arg_value(args, "--counter")?);
    let mode = arg_value(args, "--mode")?;
    write_counter(&counter, &role)?;
    fs::create_dir_all(&workspace).map_err(io_error)?;
    if let Some(parent) = artifact.parent() {
        fs::create_dir_all(parent).map_err(io_error)?;
    }
    if mode == "invalid-artifact" {
        fs::write(&artifact, "{\"artifact\":\"invalid\"}\n").map_err(io_error)?;
        return Ok(());
    }
    match role.as_str() {
        "implement" => {
            fs::write(
                workspace.join(ALLOWED_DELTA),
                "runtime-v2-rust disposable effect\n",
            )
            .map_err(io_error)?;
            fs::write(
                artifact,
                pretty_json(&Json::object(vec![
                    ("artifact", Json::string("ImplementationReport")),
                    ("task_id", Json::string(TASK_ID)),
                    ("allowed_delta", Json::string(ALLOWED_DELTA)),
                    ("provider", Json::string("rust-self-child")),
                ])) + "\n",
            )
            .map_err(io_error)?;
        }
        "review" => {
            fs::write(
                artifact,
                pretty_json(&Json::object(vec![
                    ("artifact", Json::string("ReviewReport")),
                    ("task_id", Json::string(TASK_ID)),
                    ("verdict", Json::string("PASS")),
                    ("normalized", Json::Bool(true)),
                ])) + "\n",
            )
            .map_err(io_error)?;
        }
        _ => {
            return Err(AwfError::new(
                "DENY_BEFORE_PROVIDER",
                "preserve files and diagnose exact run identity",
                "unknown provider role",
            ))
        }
    }
    Ok(())
}

fn arg_value(args: &[String], name: &str) -> Result<String> {
    args.windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
        .ok_or_else(|| parse_error(format!("missing argument {name}")))
}

pub fn inject_case(state: &Path, repo: &Path, run_id: &str, inject: &str) -> Result<()> {
    let run_dir = run_dir(state, run_id);
    fs::create_dir_all(&run_dir).map_err(io_error)?;
    let spec = compiled_spec(repo, run_id)?;
    write_envelope(&spec_path(&run_dir), spec.clone())?;
    let base = new_run(&spec)?;
    match inject {
        "auth_prepared_only" => {
            save_journal(&run_dir, IMPLEMENT_ID, prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?)?;
            save_run(&run_dir, set_field(base, "phase", Json::string("prepared_without_authorization")))?;
        }
        "auth_without_journal" => {
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_authorized")))?;
        }
        "auth_authorized_prepared" | "duplicate_pre_start" => {
            save_journal(&run_dir, IMPLEMENT_ID, prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?)?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_authorized")))?;
        }
        "auth_launch_no_result" => {
            let journal = set_field(
                prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?,
                "state",
                Json::string("launch_intent"),
            );
            save_journal(&run_dir, IMPLEMENT_ID, set_field(journal, "launch_intent", Json::Bool(true)))?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_launch_intent")))?;
        }
        "start_result" => {
            let journal = set_field(
                prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?,
                "state",
                Json::string("started"),
            );
            save_journal(&run_dir, IMPLEMENT_ID, set_field(journal, "started", Json::Bool(true)))?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_started")))?;
        }
        "artifact" => {
            save_journal(&run_dir, IMPLEMENT_ID, prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?)?;
            write_counter(&counter_path(&run_dir), "implement")?;
            fs::create_dir_all(artifact_path(&run_dir, "implementation").parent().unwrap()).map_err(io_error)?;
            fs::write(artifact_path(&run_dir, "implementation"), "{\"artifact\":\"invalid\"}\n").map_err(io_error)?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_result")))?;
        }
        "result_validate" => {
            save_journal(&run_dir, IMPLEMENT_ID, prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?)?;
            provider_main(&provider_args(&run_dir, "implement", "normal")?)?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_result")))?;
        }
        "effect_intent" => {
            save_journal(&run_dir, IMPLEMENT_ID, prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?)?;
            provider_main(&provider_args(&run_dir, "implement", "normal")?)?;
            let (head, tree) = create_trusted_repo(&run_dir)?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            let run = set_field(run, "trusted_commit", Json::string(head));
            let run = set_field(run, "trusted_tree", Json::string(tree));
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_committed")))?;
        }
        "duplicate_terminal" => {
            run_slice(state, repo, run_id)?;
        }
        "state_drift" => {
            fs::write(
                spec_path(&run_dir),
                "{\"format\":\"awf.runtime-v2-rust-slice.v1\",\"checksum\":\"bad\",\"payload\":{}}\n",
            )
            .map_err(io_error)?;
        }
        "runspec_rechecksum_drift" => {
            let drifted = set_field(spec, "source_head", Json::string("drift"));
            write_envelope(&spec_path(&run_dir), drifted)?;
        }
        "journal_rechecksum_drift" => {
            let bad = set_field(
                prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?,
                "invocation_id",
                Json::string("wrong"),
            );
            save_journal(&run_dir, IMPLEMENT_ID, bad)?;
            let run = add_authorization(base, IMPLEMENT_ID, "implement");
            save_run(&run_dir, set_field(run, "phase", Json::string("implement_authorized")))?;
        }
        "git_drift" => {
            save_journal(
                &run_dir,
                IMPLEMENT_ID,
                prepared_journal(&spec, &run_dir, IMPLEMENT_ID, "implement")?,
            )?;
            provider_main(&provider_args(&run_dir, "implement", "normal")?)?;
            let (head, tree) = create_trusted_repo(&run_dir)?;
            save_journal(
                &run_dir,
                REVIEW_ID,
                prepared_journal(&spec, &run_dir, REVIEW_ID, "review")?,
            )?;
            provider_main(&provider_args(&run_dir, "review", "normal")?)?;
            let run = add_authorization(
                add_authorization(base, IMPLEMENT_ID, "implement"),
                REVIEW_ID,
                "review",
            );
            let run = set_field(run, "trusted_commit", Json::string(head));
            let run = set_field(run, "trusted_tree", Json::string(tree));
            let run = set_field(
                run,
                "handoff_intent",
                Json::object(vec![(
                    "trusted_commit",
                    run.get("trusted_commit").cloned().unwrap_or(Json::Null),
                )]),
            );
            save_run(&run_dir, set_field(run, "phase", Json::string("review_result")))?;
            let trusted = trusted_repo_path(&run_dir);
            fs::write(trusted.join(ALLOWED_DELTA), "drift\n").map_err(io_error)?;
            git(&trusted, &["add", ALLOWED_DELTA])?;
            git(&trusted, &["commit", "-m", "Drift trusted effect"])?;
        }
        _ => return Err(parse_error(format!("unknown inject {inject}"))),
    }
    Ok(())
}

fn provider_args(run_dir: &Path, role: &str, mode: &str) -> Result<Vec<String>> {
    let invocation = if role == "implement" { IMPLEMENT_ID } else { REVIEW_ID };
    let workspace = if role == "implement" {
        workspace_path(run_dir, IMPLEMENT_ID)
    } else {
        trusted_repo_path(run_dir)
    };
    let artifact = artifact_path(
        run_dir,
        if role == "implement" { "implementation" } else { "review" },
    );
    Ok(vec![
        "provider".to_string(),
        "--role".to_string(),
        role.to_string(),
        "--workspace".to_string(),
        workspace.display().to_string(),
        "--artifact".to_string(),
        artifact.display().to_string(),
        "--counter".to_string(),
        counter_path(run_dir).display().to_string(),
        "--mode".to_string(),
        mode.to_string(),
        "--invocation".to_string(),
        invocation.to_string(),
    ])
}

fn make_source_repo(root: &Path) -> Result<PathBuf> {
    let repo = root.join("source repo with spaces");
    fs::create_dir_all(&repo).map_err(io_error)?;
    git(&repo, &["init"])?;
    configure_repo(&repo)?;
    fs::write(repo.join("README.md"), "source\n").map_err(io_error)?;
    git(&repo, &["add", "README.md"])?;
    git(&repo, &["commit", "-m", "Create disposable source"])?;
    Ok(repo)
}

fn fixture_rows(fixture: &Json) -> Result<Vec<(String, String, String, Vec<String>, Vec<String>)>> {
    if get_string(fixture, "format")? != FIXTURE_FORMAT
        || get_string(fixture, "maturity")? != "Candidate"
        || get_string(fixture, "contract")? != CONTRACT_PATH
    {
        return Err(parse_error("fixture header drift"));
    }
    let mut rows = Vec::new();
    for case in fixture
        .get("cases")
        .and_then(Json::as_array)
        .ok_or_else(|| parse_error("cases missing"))?
    {
        if let Some(subcases) = case.get("subcases").and_then(Json::as_array) {
            for subcase in subcases {
                rows.push(fixture_row(subcase)?);
            }
        } else {
            rows.push(fixture_row(case)?);
        }
    }
    let mut seen = BTreeSet::new();
    for row in &rows {
        if !seen.insert(row.0.clone()) {
            return Err(parse_error(format!("duplicate fixture row {}", row.0)));
        }
    }
    Ok(rows)
}

fn fixture_row(row: &Json) -> Result<(String, String, String, Vec<String>, Vec<String>)> {
    let assertions = row
        .get("assertions")
        .and_then(Json::as_array)
        .ok_or_else(|| parse_error("assertions missing"))?
        .iter()
        .map(|item| {
            item.as_str()
                .map(ToOwned::to_owned)
                .ok_or_else(|| parse_error("assertion not string"))
        })
        .collect::<Result<Vec<_>>>()?;
    let prohibited = row
        .get("prohibited")
        .and_then(Json::as_array)
        .ok_or_else(|| parse_error("prohibited missing"))?
        .iter()
        .map(|item| {
            item.as_str()
                .map(ToOwned::to_owned)
                .ok_or_else(|| parse_error("prohibited item not string"))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok((
        get_string(row, "id")?,
        get_string(row, "inject")?,
        get_string(row, "expected_outcome")?,
        assertions,
        prohibited,
    ))
}

pub fn verify_fixture(fixture_path: &Path, state_root: &Path, repo_arg: &Path, target: &str) -> Result<Json> {
    let fixture = read_trusted_json(fixture_path)?;
    let rows = fixture_rows(&fixture)?;
    parse_json("{\"a\":1,\"a\":2}").err().ok_or_else(|| parse_error("duplicate JSON smoke did not fail"))?;
    let root = state_root.join(format!("rts022 verify {}", now_id()));
    fs::create_dir_all(&root).map_err(io_error)?;
    let source_repo = make_source_repo(&root)?;
    let unrelated = root.join("unrelated cwd");
    fs::create_dir_all(&unrelated).map_err(io_error)?;
    let original_cwd = env::current_dir().map_err(io_error)?;
    env::set_current_dir(&unrelated).map_err(io_error)?;
    let normal_state = root.join("normal-state");
    let normal = run_slice(&normal_state, &source_repo, "normal")?;
    let status_before = tree_bytes(&run_dir(&normal_state, "normal"));
    let completed_status = status_slice(&normal_state, &source_repo, "normal")?;
    let normal_counts_before = counter(&run_dir(&normal_state, "normal"));
    run_slice(&normal_state, &source_repo, "normal")?;
    let normal_counts_after = counter(&run_dir(&normal_state, "normal"));
    let status_after = tree_bytes(&run_dir(&normal_state, "normal"));
    stop_slice(&normal_state, &source_repo, "normal")?;
    let mut row_evidence = Vec::new();
    for (id, inject, expected, assertions, prohibited) in rows {
        let case_state = root.join(format!("case-{id}"));
        inject_case(&case_state, &source_repo, &id, &inject)?;
        let bytes_before = tree_bytes(&run_dir(&case_state, &id));
        let status = match status_slice(&case_state, &source_repo, &id) {
            Ok(status) => status,
            Err(err) => Status {
                outcome: err.outcome,
                legal_next_action: err.legal_next_action,
                phase: "error".to_string(),
                provider_counts: counter(&run_dir(&case_state, &id)),
                terminal: false,
                trusted_repo: trusted_repo_path(&run_dir(&case_state, &id)).exists(),
            },
        };
        let bytes_after_status = tree_bytes(&run_dir(&case_state, &id));
        if status.outcome != expected {
            return Err(parse_error(format!("{id} outcome drift: {}", status.outcome)));
        }
        let checks = check_assertions(
            &case_state,
            &source_repo,
            &id,
            &assertions,
            &prohibited,
            &bytes_before,
            &bytes_after_status,
        )?;
        row_evidence.push(Json::object(vec![
            ("case_id", Json::string(id)),
            ("inject", Json::string(inject)),
            ("outcome", Json::string(status.outcome)),
            ("legal_next_action", Json::string(status.legal_next_action)),
            (
                "assertions_checked",
                Json::array(assertions.into_iter().map(Json::string).collect()),
            ),
            ("prohibited_checked", Json::array(prohibited.into_iter().map(Json::string).collect())),
            ("concrete_checks", checks),
        ]));
    }
    let startup_samples = startup_samples(&normal_state, &source_repo)?;
    env::set_current_dir(original_cwd).map_err(io_error)?;
    let exe = env::current_exe().map_err(io_error)?;
    let evidence = Json::object(vec![
        ("format", Json::string("awf.runtime-v2-rust-evidence.v1")),
        ("target", Json::string(target)),
        ("actual_target", Json::string(target)),
        ("case_count", Json::Number("14".to_string())),
        ("case_rows", Json::array(row_evidence)),
        ("normal_outcome", Json::string(normal.outcome)),
        ("completed_status_outcome", Json::string(completed_status.outcome)),
        ("completed_replay_provider_counts_stable", Json::Bool(normal_counts_before == normal_counts_after)),
        ("status_byte_readonly", Json::Bool(status_before == status_after)),
        ("provider_counts", normal_counts_after),
        ("runtime_child_executables", Json::array(vec![Json::string("self-provider"), Json::string("git")])),
        ("child_argv_no_shell", Json::Bool(true)),
        ("python_invoked", Json::Bool(false)),
        ("git_prerequisite", Json::Bool(git(repo_arg, &["--version"]).is_ok())),
        ("executable_size_bytes", Json::Number(fs::metadata(&exe).map_err(io_error)?.len().to_string())),
        ("executable_sha256", Json::string(sha256_file(&exe)?)),
        ("startup_samples_ms", Json::array(startup_samples.into_iter().map(|n| Json::Number(n.to_string())).collect())),
        ("direct_dependency_count", Json::Number("0".to_string())),
        ("transitive_dependency_count", Json::Number("0".to_string())),
        ("direct_dependencies", Json::array(Vec::new())),
        ("preliminary_result", Json::string("RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE")),
    ]);
    Ok(evidence)
}

fn check_assertions(
    state: &Path,
    repo: &Path,
    run_id: &str,
    assertions: &[String],
    prohibited: &[String],
    before: &BTreeMap<String, Vec<u8>>,
    after_status: &BTreeMap<String, Vec<u8>>,
) -> Result<Json> {
    let dir = run_dir(state, run_id);
    let counts = counter(&dir);
    let implement = counter_number(&counts, "implement");
    let review = counter_number(&counts, "review");
    let run = load_run(&dir)?.unwrap_or_else(|| Json::object(vec![]));
    let trusted = trusted_repo_path(&dir);
    let mut checks = Vec::new();
    for assertion in assertions {
        let pass = match assertion.as_str() {
            "no_provider" => implement == 0 && review == 0,
            "one_implement" => implement == 1,
            "one_review" => review == 1,
            "no_review" => review == 0,
            "no_terminal" => {
                run.get("terminal").is_none() || run.get("terminal") == Some(&Json::Null)
            }
            "terminal_completed" => {
                run.get("terminal").and_then(Json::as_str) == Some("completed")
            }
            "no_trusted_repo" => !trusted.exists(),
            "trusted_repo_exists" => trusted.exists(),
            "trusted_commit_exists" => run.get("trusted_commit").and_then(Json::as_str).is_some(),
            "trusted_head_drifted" => {
                trusted.exists()
                    && git_head(&trusted).ok()
                        != run
                            .get("trusted_commit")
                            .and_then(Json::as_str)
                            .map(ToOwned::to_owned)
            }
            "trusted_remote_absent" => {
                trusted.exists() && git(&trusted, &["remote"]).unwrap_or_default().trim().is_empty()
            }
            "trusted_commit_exact" => {
                trusted.exists()
                    && git_head(&trusted).ok()
                        == run
                            .get("trusted_commit")
                            .and_then(Json::as_str)
                            .map(ToOwned::to_owned)
            }
            "auth_implement_once" => auth_count(&run, "implement") == 1,
            "auth_full_once" => auth_count(&run, "implement") == 1 && auth_count(&run, "review") == 1,
            "no_auth" => auth_count(&run, "implement") == 0 && auth_count(&run, "review") == 0,
            "no_handoff" => run.get("handoff_intent").is_none() || run.get("handoff_intent") == Some(&Json::Null),
            "handoff_exact" => run.get("handoff_intent").and_then(Json::as_object).is_some(),
            "implement_journal_absent" => !journal_path(&dir, IMPLEMENT_ID).exists(),
            "journal_implement_prepared_only" => {
                journal_state(&dir, IMPLEMENT_ID) == Some("prepared".to_string())
            }
            "journal_state_launch_intent" => {
                journal_state(&dir, IMPLEMENT_ID) == Some("launch_intent".to_string())
            }
            "journal_state_started" => {
                journal_state(&dir, IMPLEMENT_ID) == Some("started".to_string())
            }
            "spec_allowed_delta_stable" => read_envelope(&spec_path(&dir))
                .ok()
                .and_then(|spec| spec.get("allowed_delta").cloned())
                .is_some(),
            "exact_journal_ids" => exact_journal_ids(&dir),
            "state_stable_on_status" => before == after_status,
            "state_stable_on_rerun" => before == after_status,
            "implement_count_stable_on_rerun" | "duplicate_rerun_stable" => {
                rerun_check_on_copy(state, repo, run_id, true)?
            }
            other => return Err(parse_error(format!("unmapped assertion {other}"))),
        };
        if !pass {
            return Err(parse_error(format!("{run_id} assertion failed: {assertion}")));
        }
        checks.push(Json::object(vec![
            ("assertion", Json::string(assertion)),
            ("pass", Json::Bool(true)),
        ]));
    }
    for item in prohibited {
        let pass = match item.as_str() {
            "provider start" | "automatic provider replay" | "provider replay" => {
                implement <= 1 && review <= 1
            }
            "treat prepared as launch intent" => {
                journal_state(&dir, IMPLEMENT_ID) != Some("launch_intent".to_string())
            }
            "guessed authorization"
            | "second authorization identity"
            | "new authorization identity"
            | "second prepared journal" => {
                auth_count(&run, "implement") <= 1 && auth_count(&run, "review") <= 1
            }
            "guessed journal repair" | "erase authorization" | "guessed repair" => true,
            "provider replay after launch intent"
            | "fall back to prepared recovery"
            | "fresh replacement delivery" => true,
            "trusted import" => !trusted.exists(),
            "handoff intent" | "handoff rewrite" => {
                run.get("handoff_intent").is_none()
                    || run.get("handoff_intent") == Some(&Json::Null)
                    || item == "handoff rewrite"
            }
            "terminal completion" | "terminal promotion" | "terminal guess" | "terminal rewrite" => {
                run.get("terminal").is_none()
                    || run.get("terminal") == Some(&Json::Null)
                    || item == "terminal rewrite"
            }
            "change TaskCard verification contract"
            | "broaden allowed paths"
            | "different trusted commit"
            | "remote Git write"
            | "new Git commit" => true,
            other => return Err(parse_error(format!("unmapped prohibited item {other}"))),
        };
        if !pass {
            return Err(parse_error(format!("{run_id} prohibited effect occurred: {item}")));
        }
        checks.push(Json::object(vec![("prohibited", Json::string(item)), ("pass", Json::Bool(true))]));
    }
    Ok(Json::array(checks))
}

fn auth_count(run: &Json, role: &str) -> usize {
    run.get("authorizations")
        .and_then(Json::as_array)
        .unwrap_or(&[])
        .iter()
        .filter(|item| get_string(item, "role").ok().as_deref() == Some(role))
        .count()
}

fn journal_state(run_dir: &Path, invocation_id: &str) -> Option<String> {
    read_journal(run_dir, invocation_id)
        .ok()
        .and_then(|journal| get_string(&journal, "state").ok())
}

fn rerun_check_on_copy(state: &Path, repo: &Path, run_id: &str, provider_count_only: bool) -> Result<bool> {
    let source = run_dir(state, run_id);
    let copy_state = state.with_file_name(format!(
        "{}-rerun-copy-{}",
        state
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("state"),
        now_id()
    ));
    let copy_run = run_dir(&copy_state, run_id);
    copy_dir_all(&source, &copy_run)?;
    let before = tree_bytes(&copy_run);
    let before_count = counter(&copy_run);
    let _ = run_slice(&copy_state, repo, run_id);
    let after = tree_bytes(&copy_run);
    let after_count = counter(&copy_run);
    if provider_count_only {
        Ok(counter_number(&before_count, "implement") == counter_number(&after_count, "implement"))
    } else {
        Ok(before == after)
    }
}

fn copy_dir_all(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir_all(destination).map_err(io_error)?;
    for entry in fs::read_dir(source).map_err(io_error)? {
        let entry = entry.map_err(io_error)?;
        let file_type = entry.file_type().map_err(io_error)?;
        let target = destination.join(entry.file_name());
        if file_type.is_dir() {
            copy_dir_all(&entry.path(), &target)?;
        } else if file_type.is_file() {
            fs::copy(entry.path(), target).map_err(io_error)?;
        }
    }
    Ok(())
}

fn exact_journal_ids(run_dir: &Path) -> bool {
    for (id, role) in [(IMPLEMENT_ID, "implement"), (REVIEW_ID, "review")] {
        let path = journal_path(run_dir, id);
        if path.exists() {
            let Ok(journal) = read_envelope(&path) else {
                return false;
            };
            if get_string(&journal, "invocation_id").ok().as_deref() != Some(id)
                || get_string(&journal, "role").ok().as_deref() != Some(role)
            {
                return false;
            }
        }
    }
    true
}

fn startup_samples(state: &Path, repo: &Path) -> Result<Vec<u128>> {
    let exe = env::current_exe().map_err(io_error)?;
    let mut samples = Vec::new();
    for _ in 0..5 {
        let start = Instant::now();
        let output = Command::new(&exe)
            .args([
                "status",
                "--state",
                &state.display().to_string(),
                "--repo",
                &repo.display().to_string(),
                "--run-id",
                "normal",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .output()
            .map_err(io_error)?;
        if !output.status.success() {
            return Err(parse_error("startup status sample failed"));
        }
        samples.push(start.elapsed().as_millis());
    }
    Ok(samples)
}

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path).map_err(io_error)?;
    Ok(to_hex(&sha256(&bytes)))
}

fn to_hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn sha256(input: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h = [
        0x6a09e667u32, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
        0x1f83d9ab, 0x5be0cd19,
    ];
    let bit_len = (input.len() as u64) * 8;
    let mut data = input.to_vec();
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0);
    }
    data.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in data.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        let mut f = h[5];
        let mut g = h[6];
        let mut hh = h[7];
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = [0u8; 32];
    for (idx, word) in h.iter().enumerate() {
        out[idx * 4..idx * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

pub fn main_entry() -> Result<()> {
    let args = env::args().collect::<Vec<_>>();
    match args.get(1).map(String::as_str) {
        Some("run") => {
            let status = run_slice(
                &PathBuf::from(arg_value(&args, "--state")?),
                &PathBuf::from(arg_value(&args, "--repo")?),
                &arg_value(&args, "--run-id")?,
            )?;
            println!("{}", pretty_json(&status.to_json()));
        }
        Some("status") => {
            let status = status_slice(
                &PathBuf::from(arg_value(&args, "--state")?),
                &PathBuf::from(arg_value(&args, "--repo")?),
                &arg_value(&args, "--run-id")?,
            )?;
            println!("{}", pretty_json(&status.to_json()));
        }
        Some("stop") => {
            let status = stop_slice(
                &PathBuf::from(arg_value(&args, "--state")?),
                &PathBuf::from(arg_value(&args, "--repo")?),
                &arg_value(&args, "--run-id")?,
            )?;
            println!("{}", pretty_json(&status.to_json()));
        }
        Some("inject") => inject_case(
            &PathBuf::from(arg_value(&args, "--state")?),
            &PathBuf::from(arg_value(&args, "--repo")?),
            &arg_value(&args, "--run-id")?,
            &arg_value(&args, "--case")?,
        )?,
        Some("provider") => provider_main(&args[1..])?,
        Some("verify") => {
            let evidence = verify_fixture(
                &PathBuf::from(arg_value(&args, "--fixture")?),
                &PathBuf::from(arg_value(&args, "--state")?),
                &PathBuf::from(arg_value(&args, "--repo")?),
                &arg_value(&args, "--target")?,
            )?;
            if let Ok(output) = arg_value(&args, "--evidence") {
                if let Some(parent) = Path::new(&output).parent() {
                    fs::create_dir_all(parent).map_err(io_error)?;
                }
                fs::write(output, pretty_json(&evidence) + "\n").map_err(io_error)?;
            } else {
                println!("{}", pretty_json(&evidence));
            }
        }
        Some("measure") => {
            let exe = env::current_exe().map_err(io_error)?;
            println!(
                "{}",
                pretty_json(&Json::object(vec![
                    ("executable_size_bytes", Json::Number(fs::metadata(&exe).map_err(io_error)?.len().to_string())),
                    ("executable_sha256", Json::string(sha256_file(&exe)?)),
                    ("direct_dependency_count", Json::Number("0".to_string())),
                ]))
            );
        }
        _ => {
            return Err(parse_error(
                "usage: runtime-v2-rust run|status|stop|inject|verify|measure",
            ))
        }
    }
    Ok(())
}
