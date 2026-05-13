#!/usr/bin/env bash
set -euo pipefail

REPO="${VIDEO_CARTOONIZE_REPO:-Carey8175/video-cartoonize}"
REF="${VIDEO_CARTOONIZE_REF:-main}"
INSTALL_HOME="${VIDEO_CARTOONIZE_HOME:-$HOME/.local/share/video-cartoonize}"
BIN_DIR="${VIDEO_CARTOONIZE_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_HOME/venv"
SRC_DIR="$INSTALL_HOME/src"
PYTHON_BIN="${PYTHON:-python3}"

log() {
  printf '[video-cartoonize] %s\n' "$*"
}

die() {
  printf '[video-cartoonize] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

download_source() {
  local tmp_dir="$1"
  local archive="$tmp_dir/source.tar.gz"
  local url="https://github.com/${REPO}/archive/${REF}.tar.gz"

  log "Downloading ${REPO}@${REF}"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl -fsSL -H "Authorization: token ${GITHUB_TOKEN}" "$url" -o "$archive"
  else
    curl -fsSL "$url" -o "$archive"
  fi

  mkdir -p "$SRC_DIR"
  rm -rf "$SRC_DIR"
  mkdir -p "$SRC_DIR"
  tar -xzf "$archive" -C "$tmp_dir"

  local extracted
  extracted="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d ! -name "$(basename "$SRC_DIR")" | head -n 1)"
  [[ -n "$extracted" ]] || die "failed to extract source archive"
  cp -R "$extracted"/. "$SRC_DIR"/
}

install_package() {
  log "Creating virtual environment: $VENV_DIR"
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"

  log "Installing package"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  # VIDEO_CARTOONIZE_PIP_ARGS is intentionally left unquoted after shellcheck
  # style splitting semantics: it lets CI pass flags such as --no-deps.
  # shellcheck disable=SC2086
  "$VENV_DIR/bin/python" -m pip install "$SRC_DIR" ${VIDEO_CARTOONIZE_PIP_ARGS:-}
}

install_launcher() {
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/cartoonize" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/cartoonize" "\$@"
EOF
  chmod +x "$BIN_DIR/cartoonize"
  log "Installed command: $BIN_DIR/cartoonize"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      log "Add this to your shell profile if 'cartoonize' is not found:"
      log "  export PATH=\"$BIN_DIR:\$PATH\""
      ;;
  esac
}

main() {
  require_cmd curl
  require_cmd tar
  require_cmd "$PYTHON_BIN"

  "$PYTHON_BIN" - <<'PY' || die "python3 must support venv"
import venv  # noqa: F401
PY

  INSTALL_TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$INSTALL_TMP_DIR"' EXIT

  mkdir -p "$INSTALL_HOME"
  download_source "$INSTALL_TMP_DIR"
  install_package
  install_launcher

  log "Done. Try: cartoonize --help"
}

main "$@"
