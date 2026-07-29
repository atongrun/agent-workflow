#!/usr/bin/env bash
# awf-dispatch — lightweight, safe task dispatcher for Agent Workflow.
#
# Puts a self-contained TaskCard on a PR branch and announces it on Agent Bus as a
# POINTER event. It does NOT execute anything: a long-running role listener
# (scripts/awf_listen.py) running somewhere — possibly on another machine — picks up
# the event and runs the executor. This "dispatch = announce, listener = execute"
# split is what makes execution pluggable across roles and machines.
#
# Design goals (learned from real dogfood):
#   - The card travels as a FILE via git (committed to a PR branch), never inlined into
#     a shell string or an event payload (an em-dash once corrupted an SSE event and
#     crash-looped the listener; a 200-line card also does not fit a payload).
#   - The Agent Bus event carries only a POINTER: {branch, card, commit, tool, model}.
#     The listener's handler reads those via agent-bus template placeholders.
#   - Tokens are read from the environment (sourced from a gitignored file), never CLI args.
#
# Usage:
#   scripts/awf-dispatch.sh \
#     --repo   /path/to/target-repo \
#     --card   relative/path/to/taskcard.md   (relative to --repo) \
#     --branch awf/<task-id> \
#     [--to    coder]              (recipient role; default: coder) \
#     [--tool  opencode]           (executor CLI hint for the listener; default: opencode) \
#     [--model opencode-go/deepseek-v4-flash] \
#     [--report .awf/artifacts/NN-implementation-report.md]  (impl-report path hint) \
#     [--review-report .awf/artifacts/review-report-<task-id>.md] \
#     --upstream-repo owner/repo --head-repo owner/fork \
#     [--upstream-remote upstream] [--head-remote fork] [--base-ref main] \
#     [--type  task:awf-impl-v3]   (event type; default: task:awf-impl-v3) \
#     [--no-push]                  (skip git push — LOCAL-ONLY; cross-machine needs push) \
#     [--dry-run]                  (print the event that WOULD be sent, send nothing)
#
# Agent Bus configuration is loaded by strict Python parsing of dispatch.env:
#   AGENT_BUS_URL, AWF_ARCH_TOKEN         (tokens read from env, never CLI args)
#   Optional: AWF_BUS_BIN                 (path to the agent-bus binary; default: agent-bus)
set -uo pipefail

# Load the shared configuration exactly once, without sourcing or printing it.
# Explicit process environment values win, which keeps one-shot overrides possible.
if [ "${AWF_CONFIG_LOADED:-0}" != "1" ]; then
  AWF_CONFIG_PYTHON="${AWF_PYTHON_BIN:-}"
  if [ -z "$AWF_CONFIG_PYTHON" ]; then
    case "$(uname -s 2>/dev/null || true)" in
      MINGW*|MSYS*|CYGWIN*)
        command -v python >/dev/null 2>&1 && AWF_CONFIG_PYTHON="python"
        ;;
    esac
    if [ -z "$AWF_CONFIG_PYTHON" ] && command -v python3 >/dev/null 2>&1; then
      AWF_CONFIG_PYTHON="python3"
    elif [ -z "$AWF_CONFIG_PYTHON" ] && command -v python >/dev/null 2>&1; then
      AWF_CONFIG_PYTHON="python"
    elif [ -z "$AWF_CONFIG_PYTHON" ]; then
      echo "awf-dispatch: python 3 is required to load operations configuration" >&2
      exit 2
    fi
  fi
  AWF_DISPATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
  case "$(uname -s 2>/dev/null || true)" in
    MINGW*|MSYS*|CYGWIN*)
      AWF_DISPATCH_DIR="$(cd "$(dirname "$0")" && pwd -W)"
      ;;
  esac
  exec "$AWF_CONFIG_PYTHON" "$AWF_DISPATCH_DIR/awf_config.py" --optional -- \
    bash "$0" "$@"
fi

# ---- defaults ----
REPO="" CARD="" BRANCH="" TO="coder" TOOL="opencode" MODEL="" REPORT="" REVIEW_REPORT=""
UPSTREAM_REPO="" UPSTREAM_REMOTE="upstream" HEAD_REPO="" HEAD_REMOTE="fork" BASE_REF="main"
DO_PUSH=1 DRY_RUN=0
EVENT_TYPE="task:awf-impl-v3"

die() { echo "awf-dispatch: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --card) CARD="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --to) TO="$2"; shift 2;;
    --tool) TOOL="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --report) REPORT="$2"; shift 2;;
    --review-report) REVIEW_REPORT="$2"; shift 2;;
    --upstream-repo) UPSTREAM_REPO="$2"; shift 2;;
    --upstream-remote) UPSTREAM_REMOTE="$2"; shift 2;;
    --head-repo) HEAD_REPO="$2"; shift 2;;
    --head-remote) HEAD_REMOTE="$2"; shift 2;;
    --base-ref) BASE_REF="$2"; shift 2;;
    --type) EVENT_TYPE="$2"; shift 2;;
    --no-push) DO_PUSH=0; shift;;
    --dry-run) DRY_RUN=1; shift;;
    *) die "unknown arg: $1";;
  esac
done

[ -n "$REPO" ] || die "need --repo"
[ -n "$CARD" ] || die "need --card (relative to repo)"
[ -n "$BRANCH" ] || die "need --branch"
[ -d "$REPO" ] || die "repo not found: $REPO"
[ -f "$REPO/$CARD" ] || die "card not found: $REPO/$CARD"
IS_V3=0
case "$EVENT_TYPE" in
  *-v3) IS_V3=1;;
esac
[ "$IS_V3" -eq 0 ] || [ -n "$UPSTREAM_REPO" ] || die "need --upstream-repo owner/repository"
[ "$IS_V3" -eq 0 ] || [ -n "$HEAD_REPO" ] || die "need --head-repo owner/contribution-fork"
[ "$IS_V3" -eq 0 ] || [ "$DO_PUSH" -eq 1 ] \
  || die "v3 fork/PR dispatch requires a freshly verified contribution-fork push"

# ---- 1. Put the card on a PR branch and push (the card travels via git, not the event) ----
echo "[dispatch] repo=$REPO card=$CARD branch=$BRANCH to=$TO tool=$TOOL model=${MODEL:-<default>}"
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "repo is not a git work tree"
AWF_PYTHON="${AWF_PYTHON_BIN:-}"
if [ -z "$AWF_PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    AWF_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    AWF_PYTHON="python"
  else
    die "python 3 is required to validate trusted Git configuration"
  fi
fi
if [ "$IS_V3" -eq 1 ]; then
  "$AWF_PYTHON" -c 'import re,subprocess,sys,urllib.parse
repo,up_slug,up_remote,head_slug,head_remote,base_ref,head_ref=sys.argv[1:]
slug=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9_.-]{1,100}$")
remote=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
def require(condition):
 if not condition:
  raise SystemExit(2)
require(slug.fullmatch(up_slug) and slug.fullmatch(head_slug))
require(remote.fullmatch(up_remote) and remote.fullmatch(head_remote))
require(up_slug.casefold()!=head_slug.casefold() and up_remote!=head_remote)
for ref in (base_ref,head_ref):
 p=subprocess.run(["git","-C",repo,"check-ref-format","--branch",ref],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 require(p.returncode==0 and not ref.startswith(("refs/","-")))
for name,expected in ((up_remote,up_slug),(head_remote,head_slug)):
 p=subprocess.run(["git","-C",repo,"remote","get-url",name],capture_output=True,text=True,encoding="utf-8")
 require(p.returncode==0)
 fetch_url=p.stdout.strip()
 u=urllib.parse.urlsplit(fetch_url)
 require(u.scheme=="https" and u.hostname=="github.com" and u.username is None and u.password is None and u.port is None)
 require(not u.query and not u.fragment and u.path in (f"/{expected}",f"/{expected}.git"))
 p=subprocess.run(["git","-C",repo,"remote","get-url","--push","--all",name],capture_output=True,text=True,encoding="utf-8")
 require(p.returncode==0 and p.stdout.splitlines()==[fetch_url])' \
  "$REPO" "$UPSTREAM_REPO" "$UPSTREAM_REMOTE" "$HEAD_REPO" "$HEAD_REMOTE" "$BASE_REF" "$BRANCH" \
  >/dev/null 2>&1 || die "invalid or untrusted GitHub remote/repository/ref configuration"
fi

cur_branch="$(git -C "$REPO" branch --show-current)"
if [ "$cur_branch" != "$BRANCH" ]; then
  git -C "$REPO" checkout -B "$BRANCH" >/dev/null 2>&1 || die "cannot checkout branch $BRANCH"
fi
git -C "$REPO" add -- "$CARD" || die "git add failed"
if ! git -C "$REPO" diff --cached --quiet; then
  git -C "$REPO" commit -q -m "chore(awf): dispatch TaskCard $CARD" || die "commit failed"
fi
COMMIT="$(git -C "$REPO" rev-parse HEAD)"
if [ "$DO_PUSH" -eq 1 ]; then
  if [ "$IS_V3" -eq 1 ]; then
    git -C "$REPO" push -u "$HEAD_REMOTE" "HEAD:refs/heads/$BRANCH" >/dev/null 2>&1 \
      || die "fork push failed; refusing to send an event for an unavailable TaskCard"
    git -C "$REPO" fetch --no-tags "$HEAD_REMOTE" \
      "+refs/heads/$BRANCH:refs/remotes/$HEAD_REMOTE/$BRANCH" >/dev/null 2>&1 \
      || die "cannot freshly verify the TaskCard fork ref"
  else
    git -C "$REPO" push -u origin "$BRANCH" >/dev/null 2>&1 \
      || die "push failed; refusing to send an event for a TaskCard the remote executor cannot fetch"
  fi
else
  echo "[dispatch] --no-push: LOCAL-ONLY. A remote (e.g. Windows) executor cannot pull this card."
fi
if [ "$IS_V3" -eq 1 ]; then
  HEAD_SHA="$(git -C "$REPO" rev-parse --verify "refs/remotes/$HEAD_REMOTE/$BRANCH^{commit}")"
  [ "$HEAD_SHA" = "$COMMIT" ] || die "fresh TaskCard fork SHA does not match local HEAD"
  git -C "$REPO" fetch --no-tags "$UPSTREAM_REMOTE" \
    "+refs/heads/$BASE_REF:refs/remotes/$UPSTREAM_REMOTE/$BASE_REF" >/dev/null 2>&1 \
    || die "cannot fetch the trusted upstream base"
  BASE_SHA="$(git -C "$REPO" rev-parse --verify "refs/remotes/$UPSTREAM_REMOTE/$BASE_REF^{commit}")"
fi
echo "[dispatch] card committed at $COMMIT on $BRANCH"

# ---- 2. Send the Agent Bus event (pointer only) ----
task_id="${BRANCH##*/}"
# report path hint: default to a conventional per-task artifact path if not given.
[ -n "$REPORT" ] || REPORT=".awf/artifacts/impl-report-$task_id.md"
[ -n "$REVIEW_REPORT" ] || REVIEW_REPORT=".awf/artifacts/review-report-$task_id.md"
if [ "$IS_V3" -eq 1 ]; then
  payload="$("$AWF_PYTHON" -c 'import hashlib,json,sys; keys=("task_id","branch","card","commit","tool","model","report","review_report","provenance_version","upstream_repo","base_ref","base_sha","head_repo","head_ref","head_sha","pull_request"); p=dict(zip(keys,sys.argv[2:])); p["pull_request"]=int(p["pull_request"]); c=lambda v: json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")); h="sha256:"+hashlib.sha256(c(p).encode()).hexdigest(); s={"format":"awf.delivery.v1","source_role":"architect","event_type":sys.argv[1],"payload_sha256":h,"source_event_id":0}; p.update(awf_delivery_id="awf:"+hashlib.sha256(c(s).encode()).hexdigest(),awf_payload_sha256=h,awf_source_event_id=0); print(c(p))' \
    "$EVENT_TYPE" "$task_id" "$BRANCH" "$CARD" "$COMMIT" "$TOOL" "$MODEL" "$REPORT" "$REVIEW_REPORT" \
    "awf.pr-provenance.v1" "$UPSTREAM_REPO" "$BASE_REF" "$BASE_SHA" "$HEAD_REPO" "$BRANCH" "$HEAD_SHA" "0")" \
    || die "cannot compute Workflow delivery metadata"
else
  payload="$("$AWF_PYTHON" -c 'import hashlib,json,sys; p=dict(zip(("task_id","branch","card","commit","tool","model","report","review_report"),sys.argv[2:])); c=lambda v: json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")); h="sha256:"+hashlib.sha256(c(p).encode()).hexdigest(); s={"format":"awf.delivery.v1","source_role":"architect","event_type":sys.argv[1],"payload_sha256":h,"source_event_id":0}; p.update(awf_delivery_id="awf:"+hashlib.sha256(c(s).encode()).hexdigest(),awf_payload_sha256=h,awf_source_event_id=0); print(c(p))' \
    "$EVENT_TYPE" "$task_id" "$BRANCH" "$CARD" "$COMMIT" "$TOOL" "$MODEL" "$REPORT" "$REVIEW_REPORT")" \
    || die "cannot compute Workflow delivery metadata"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dispatch] --dry-run: would send event"
  echo "           type=$EVENT_TYPE  from=architect  to=$TO"
  echo "           payload=$payload"
  echo "[dispatch] (dry-run) nothing sent."
  exit 0
fi

: "${AGENT_BUS_URL:?set AGENT_BUS_URL or create strict dispatch.env}"
: "${AWF_ARCH_TOKEN:?set AWF_ARCH_TOKEN or create strict dispatch.env}"
AWF_BUS="${AWF_BUS_BIN:-agent-bus}"
bus_host="${AGENT_BUS_URL#*://}"
bus_host="${bus_host%%/*}"
bus_host="${bus_host%%:*}"
bus_no_proxy="${NO_PROXY:-${no_proxy:-}}"
if [ -n "${NO_PROXY:-}" ] && [ -n "${no_proxy:-}" ] && [ "$NO_PROXY" != "$no_proxy" ]; then
  bus_no_proxy="$NO_PROXY,$no_proxy"
fi
case ",$bus_no_proxy," in
  *",$bus_host,"*) ;;
  *) bus_no_proxy="${bus_no_proxy:+$bus_no_proxy,}$bus_host";;
esac
AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$AWF_ARCH_TOKEN" AGENT_BUS_AGENT=architect \
  NO_PROXY="$bus_no_proxy" no_proxy="$bus_no_proxy" \
  "$AWF_BUS" send --from architect --to "$TO" --type "$EVENT_TYPE" --payload "$payload" \
  || die "agent-bus send failed"
echo "[dispatch] event sent (type=$EVENT_TYPE to=$TO). A '$TO' listener will pick it up and execute."
