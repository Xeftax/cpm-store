#!/usr/bin/env bash
# The one gitleaks definition: this file owns the version, the checksum verification and
# the scan invocation, for both the pre-commit hook and the CI gate.
#
# Usage:
#   secret-scan.sh                       picks one of the three below from the environment
#   secret-scan.sh --staged              what is about to be committed (the hook)
#   secret-scan.sh --range <A>..<B>      the commits an event brought in (the gate)
#   secret-scan.sh --full [report.json]  the whole history, advisory (the weekly cron)
#   secret-scan.sh --hook                what a Claude Code session left uncommitted, payload
#                                        on stdin — see lib/hook-mode.sh
#
# There used to be two declarations of the same version with nothing comparing them:
# `rev: v8.30.1` in `.pre-commit-config.yaml`, and a `GITLEAKS_VERSION` default in the
# gitleaks action. They agreed, which is exactly why the drift would have been silent —
# a bump on one side leaves a developer's hook and the merge gate enforcing different
# rulesets, and the first evidence is a secret that passed locally and blocked a PR, or
# worse, the reverse.
#
# Deciding WHICH scan an event calls for lives here too, below the binary resolution: it
# reads the GitHub event payload when there is one, so the hook and the `gitleaks` check
# run the same command with no argument of their own.
#
# The binary is verified against the published checksums, not merely fetched over HTTPS:
# HTTPS proves the transport was not tampered with, not that the release artifact is the
# one that was published. `--redact` on every scan below — without it a finding is
# printed in clear text into a log that is readable by anyone with Actions access and
# kept indefinitely, which is the exposure the scan exists to catch. File, line, rule and
# commit stay visible, so a finding is still actionable.
set -euo pipefail

GITLEAKS_VERSION="8.30.1"

usage() {
  echo "usage: secret-scan.sh [--staged | --range <A>..<B> | --full [report-path] | --hook]" >&2
  exit 2
}

# --- resolve a verified gitleaks binary ------------------------------------------------
#
# A gitleaks already on PATH is used only when it is the pinned version: a developer with
# an older one installed would otherwise be running a different ruleset from CI, which is
# the whole defect this file closes. Anything else is fetched into a per-version cache
# directory, so the download happens once per machine rather than once per commit, and
# `sudo mv /usr/local/bin` — which the gate did, and which no hook can do — is not needed.
#
# This function assigns $GITLEAKS rather than printing the path for a caller to capture,
# and that is load-bearing rather than style. It was written as `GITLEAKS="$(resolve…)"`,
# which runs the whole body in a command substitution — a subshell where **bash 3.2 does
# not honour `set -e`**, and 3.2 is the system bash on every macOS, so it is what
# `#!/usr/bin/env bash` resolves to on a developer's machine. Nothing in here aborted:
# not curl, not the checksum, not tar. A valid tarball whose SHA-256 did not match was
# installed, cached and executed, and the script exited 0 — with the mismatch printed to
# the log above it. The cache is keyed by version and short-circuits on `[[ -x ]]`, so one
# poisoned download would have pinned that binary for every later commit on the machine.
#
# Assigning a global keeps the body in the main shell where `set -e` applies. The explicit
# `|| exit` on each fallible step is belt-and-braces on top: a verification step must not
# depend on which bash is running, and the failure has to name itself rather than surface
# four lines later as a confusing `tar` error.
GITLEAKS=""
_download_dir=""
# The status is captured first and re-raised last: with nothing downloaded, the `[[ ]]`
# test is false, and an EXIT trap ending on a false command replaced the script's own
# status with 1 — a usage error (2) read as a finding.
cleanup_download() {
  local status=$?
  if [[ -n "$_download_dir" ]]; then rm -rf "$_download_dir"; fi
  exit "$status"
}
trap cleanup_download EXIT

resolve_gitleaks() {
  if command -v gitleaks > /dev/null 2>&1 \
    && [[ "$(gitleaks version 2> /dev/null | tr -d 'v[:space:]')" == "$GITLEAKS_VERSION" ]]; then
    GITLEAKS="$(command -v gitleaks)"
    return
  fi

  local cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/dockyard/gitleaks/${GITLEAKS_VERSION}"
  local binary="${cache_dir}/gitleaks"
  if [[ -x "$binary" ]]; then
    GITLEAKS="$binary"
    return
  fi

  local os arch
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) echo "secret-scan.sh: unsupported OS $(uname -s)" >&2; exit 1 ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64 ;;
    arm64 | aarch64) arch=arm64 ;;
    *) echo "secret-scan.sh: unsupported architecture $(uname -m)" >&2; exit 1 ;;
  esac

  local archive="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
  local base="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
  # The cache directory is left behind on purpose; the download directory is not.
  _download_dir="$(mktemp -d)"
  local tmp="$_download_dir"

  echo "secret-scan.sh: fetching gitleaks ${GITLEAKS_VERSION} (${os}_${arch})" >&2
  curl --proto '=https' --tlsv1.2 -sSfL -o "${tmp}/${archive}" "${base}/${archive}" \
    || { echo "secret-scan.sh: could not download ${archive}" >&2; exit 1; }
  curl --proto '=https' --tlsv1.2 -sSfL -o "${tmp}/checksums.txt" \
    "${base}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
    || { echo "secret-scan.sh: could not download the published checksums" >&2; exit 1; }

  # `shasum -a 256` rather than `sha256sum`: macOS ships the former and not the latter,
  # and this script runs on a developer's machine as well as on a runner.
  local sha_tool
  if command -v sha256sum > /dev/null 2>&1; then
    sha_tool=(sha256sum -c -)
  else
    sha_tool=(shasum -a 256 -c -)
  fi
  # The `grep` matters as much as the checksum: an archive name absent from the published
  # list feeds an empty line to the checker, and with pipefail off that would verify
  # nothing at all. Both halves of the pipeline are fatal.
  (cd "$tmp" && grep " ${archive}\$" checksums.txt | "${sha_tool[@]}") > /dev/null \
    || { echo "secret-scan.sh: CHECKSUM MISMATCH for ${archive} — refusing to install it" >&2; exit 1; }

  tar -xzf "${tmp}/${archive}" -C "$tmp" gitleaks \
    || { echo "secret-scan.sh: could not extract ${archive}" >&2; exit 1; }
  mkdir -p "$cache_dir" || exit 1
  # Published atomically: two hooks firing at once must never see a half-written binary.
  mv "${tmp}/gitleaks" "${binary}.$$" || exit 1
  chmod +x "${binary}.$$" || exit 1
  mv "${binary}.$$" "$binary" || exit 1
  GITLEAKS="$binary"
}

# No argument: the mode is read off where the script runs, so the pre-commit hook and the
# `gitleaks` check run the same command. Off a runner it is the staged changes. On one,
# the event's own range — each event names its base and head in a different field — and
# the full history on a schedule or a dispatch, which is where a secret committed and
# then deleted still lives. A first push to a branch carries an all-zero `before`, and a
# range from it would re-scan the whole history, pre-existing findings included, so it
# scans the pushed commit alone.
if [[ $# -eq 0 ]]; then
  event_field() { jq -r "$1 // empty" "${GITHUB_EVENT_PATH:?}"; }
  # Both ends, read before `set --` so a missing one is caught: `..` alone scans nothing
  # and would report a clean scan.
  range_of() {
    local base head
    base="$(event_field "$1")" && head="$(event_field "$2")" || exit 2
    if [[ -z "$base" || -z "$head" ]]; then
      echo "secret-scan.sh: the $GITHUB_EVENT_NAME event names no range ($1, $2)" >&2
      exit 2
    fi
    echo "${base}..${head}"
  }
  case "${GITHUB_EVENT_NAME:-}" in
    "") set -- --staged ;;
    pull_request)
      range="$(range_of .pull_request.base.sha .pull_request.head.sha)"
      set -- --range "$range"
      ;;
    merge_group)
      range="$(range_of .merge_group.base_sha .merge_group.head_sha)"
      set -- --range "$range"
      ;;
    push)
      before="$(event_field .before)"
      case "$before" in
        "" | 0000000000000000000000000000000000000000) set -- --range "-1 HEAD" ;;
        *)
          range="$(range_of .before .after)"
          set -- --range "$range"
          ;;
      esac
      ;;
    schedule | workflow_dispatch) set -- --full gitleaks-report.json ;;
    *)
      echo "secret-scan.sh: no scan defined for the $GITHUB_EVENT_NAME event" >&2
      exit 2
      ;;
  esac
fi

[[ $# -ge 1 ]] || usage
mode="$1"
shift

# The files are collected before the binary is resolved: a clean tree must never cost a
# download, and a session's Stop fires dozens of times.
if [[ "$mode" == --hook ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  hook_files files .
  [[ ${#files[@]} -gt 0 ]] || exit 0
fi

# The fingerprints `dockyard.toml`'s `[gitleaks] ignore` renders. Passed by name so a scan
# from a subdirectory or a different `--source` still reads them, and only when the file is
# there: gitleaks refuses a path that does not exist.
ignore_args=()
if [[ -f .gitleaksignore ]]; then ignore_args=(--gitleaks-ignore-path .gitleaksignore); fi

resolve_gitleaks
[[ -n "$GITLEAKS" && -x "$GITLEAKS" ]] \
  || { echo "secret-scan.sh: no verified gitleaks binary — refusing to report a clean scan" >&2; exit 1; }

case "$mode" in
  --hook)
    # One `gitleaks dir` per uncommitted file — the working tree is what a session wrote,
    # and nothing of it reaches history before pre-commit's own `--staged` run. The
    # config is named because a single-file source does not discover it.
    config=()
    [[ -f .gitleaks.toml ]] && config=(--config .gitleaks.toml)
    status=0
    for f in "${files[@]}"; do
      "$GITLEAKS" dir "$f" --no-banner --redact "${config[@]+"${config[@]}"}" ${ignore_args[@]+"${ignore_args[@]}"} || status=1
    done
    exit "$status"
    ;;
  --staged)
    # `git --staged` is what the hook wants: the working tree may hold anything, only
    # what is about to enter history is blocking.
    exec "$GITLEAKS" git --pre-commit --staged --no-banner --redact --verbose ${ignore_args[@]+"${ignore_args[@]}"}
    ;;
  --range)
    [[ $# -ge 1 ]] || usage
    # gitleaks logs an unresolvable range and still exits 0 having scanned nothing — a
    # force-pushed or unfetched `before` would read as a clean scan. Both ends must exist.
    if [[ "$1" == *..* ]]; then
      for end in "${1%%..*}" "${1##*..}"; do
        git rev-parse --verify --quiet "${end}^{commit}" > /dev/null \
          || { echo "secret-scan.sh: cannot resolve $end in this clone — refusing to report a clean scan" >&2; exit 1; }
      done
    fi
    exec "$GITLEAKS" detect --source . --no-banner --redact --verbose --log-opts="$1" ${ignore_args[@]+"${ignore_args[@]}"}
    ;;
  --full)
    report="${1:-gitleaks-report.json}"
    exec "$GITLEAKS" detect --source . --no-banner --redact --verbose \
      --report-format json --report-path "$report" ${ignore_args[@]+"${ignore_args[@]}"}
    ;;
  *) usage ;;
esac
