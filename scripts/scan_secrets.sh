#!/usr/bin/env bash
# Secret scanner — blocks commits that would leak secrets.
#
# Checks each file argument for:
#   1) credential values from the local .env (KEY/TOKEN/SECRET/... entries, 12+ chars), and
#   2) well-known secret patterns (GitHub tokens, sk- keys, private keys, AWS keys).
#
# Usage: scripts/scan_secrets.sh <file> [file ...]
# Wired up automatically via core.hooksPath (see scripts/hooks/pre-commit).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
FOUND=0

scan_file() {
  local f="$1"
  [ -f "$f" ] || return 0

  # 1) credential values from local .env — only keys that look like credentials
  #    (URL bases are public endpoints, not secrets). Values shorter than 12
  #    chars (e.g. numeric class codes) would collide with ordinary text and
  #    are skipped; they are protected by the pattern rules below + review.
  if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r k v; do
      case "$k" in ''|\#*) continue ;; esac
      v="${v%\"}"; v="${v#\"}"
      [ -n "$v" ] || continue
      case "$k" in
        *KEY*|*TOKEN*|*SECRET*|*PASSWORD*|*PASS*|*CRED*) ;;
        *) continue ;;
      esac
      [ "${#v}" -ge 12 ] || continue
      if grep -qF "$v" "$f"; then
        echo "SECRET SCAN FAIL: '$f' contains the value of $k from .env" >&2
        FOUND=1
      fi
    done < "$ENV_FILE"
  fi

  # 2) known secret patterns
  if grep -qE '(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{16,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16})' "$f"; then
    echo "SECRET SCAN FAIL: '$f' matches a known secret pattern (gh_/sk-/private key/AWS)" >&2
    FOUND=1
  fi
}

for f in "$@"; do
  scan_file "$f"
done

if [ "$FOUND" -ne 0 ]; then
  echo "Commit blocked: remove the secret from the staged files (or rotate the key if it leaked)." >&2
  exit 1
fi
exit 0
