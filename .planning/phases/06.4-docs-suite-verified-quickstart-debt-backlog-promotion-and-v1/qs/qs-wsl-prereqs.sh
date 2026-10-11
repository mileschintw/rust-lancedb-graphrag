#!/usr/bin/env bash
# WSL prerequisites for the README quickstart (06.4 plan 10, D-231, D-220).
#
#   qs-wsl-prereqs.sh --check     print present or missing plus the version for each prerequisite;
#                                 exit 0 only when every item is present and Go is 1.25 or later
#   qs-wsl-prereqs.sh --install   run the README's WSL prerequisite commands, verbatim in effect
#
# D-231: privileged commands run only through the non-interactive form of sudo ("sudo -n"), or bare
# when this script already runs as root (wsl.exe -d Ubuntu -u root). No password is ever read,
# typed, piped or prompted for. When non-interactive sudo is unavailable for the default user the
# script exits 3 and the caller reruns it as root.
#
# Exit codes: 0 ok; 1 a prerequisite is missing (--check) or an install step failed; 2 usage;
# 3 "sudo -n unavailable".
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/go/bin:$PATH"

GO_MIN="1.25"
GO_PIN="1.26.5"
GO_TARBALL="go1.26.5.linux-amd64.tar.gz"
GO_URL="https://go.dev/dl/go1.26.5.linux-amd64.tar.gz"

# True (0) when "$1" is a version at or above $GO_MIN, compared with sort -V.
version_at_least_go_min() {
  local have="$1"
  [ -n "$have" ] || return 1
  [ "$(printf '%s\n%s\n' "$GO_MIN" "$have" | sort -V | head -n 1)" = "$GO_MIN" ]
}

go_version() {
  # "go1.26.5" -> "1.26.5"; empty when go is absent.
  if command -v go >/dev/null 2>&1; then
    go env GOVERSION 2>/dev/null | sed 's/^go//'
  fi
}

check() {
  local missing=0 v
  report() { # name, status, detail
    printf '%-12s %-8s %s\n' "$1" "$2" "$3"
  }
  have_cmd() { # name, version command
    local name="$1"; shift
    if command -v "$name" >/dev/null 2>&1; then
      v="$("$@" 2>&1 | head -n 1 || true)"
      report "$name" present "$v"
    else
      report "$name" missing ""
      missing=1
    fi
  }
  have_cmd pkg-config pkg-config --version
  have_cmd protoc protoc --version
  if dpkg -s libssl-dev 2>/dev/null | grep -q '^Status: install ok installed'; then
    report libssl-dev present "$(dpkg -s libssl-dev | sed -n 's/^Version: //p')"
  else
    report libssl-dev missing ""
    missing=1
  fi
  if command -v go >/dev/null 2>&1; then
    v="$(go_version)"
    if version_at_least_go_min "$v"; then
      report go present "$v (needs ${GO_MIN} or later; pinned ${GO_PIN})"
    else
      report go old "$v (older than ${GO_MIN})"
      missing=1
    fi
  else
    report go missing ""
    missing=1
  fi
  have_cmd atlas atlas version
  have_cmd uv uv --version
  have_cmd cargo cargo --version
  have_cmd docker docker --version
  have_cmd git git --version
  if [ "$missing" -ne 0 ]; then
    echo "RESULT: at least one prerequisite is missing or too old"
    return 1
  fi
  echo "RESULT: every prerequisite is present"
}

# Sets SUDO to "sudo -n" (default user, passwordless sudo works) or "" (already root).
resolve_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
    echo "route: root (wsl -u root)"
  elif sudo -n true 2>/dev/null; then
    SUDO="sudo -n"
    echo "route: sudo -n"
  else
    echo "sudo -n unavailable" >&2
    exit 3
  fi
}

install() {
  local SUDO
  resolve_sudo
  # README: sudo apt-get install -y pkg-config libssl-dev protobuf-compiler
  $SUDO apt-get install -y pkg-config libssl-dev protobuf-compiler
  # README: the pinned Go toolchain from the official tarball. Skipped when a Go 1.25 or later is
  # already installed, so a rerun does not download it again.
  if version_at_least_go_min "$(go_version)"; then
    echo "go: $(go_version) already present, not reinstalled"
  else
    curl -fsSLo "/tmp/${GO_TARBALL}" "$GO_URL"
    $SUDO rm -rf /usr/local/go
    $SUDO tar -C /usr/local -xzf "/tmp/${GO_TARBALL}"
  fi
  # README: curl -sSf https://atlasgo.sh | sh. The installer writes into /usr/local/bin, so the shell
  # that runs it is the privileged one.
  if command -v atlas >/dev/null 2>&1; then
    echo "atlas: already present, not reinstalled"
  else
    curl -sSf https://atlasgo.sh | $SUDO sh
  fi
}

case "${1:-}" in
  --check) check ;;
  --install) install ;;
  *) echo "usage: qs-wsl-prereqs.sh --check | --install" >&2; exit 2 ;;
esac
