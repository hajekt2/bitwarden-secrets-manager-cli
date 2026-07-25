#!/bin/sh

set -eu

if command -v bws >/dev/null 2>&1; then
  bws --version
  exit 0
fi

case "$(uname -s)" in
  Linux | Darwin) ;;
  *)
    printf '%s\n' \
      "bws is not installed and this helper supports Linux and macOS." \
      "On native Windows, run the official PowerShell installer:" \
      "  iwr https://bws.bitwarden.com/install | iex" >&2
    exit 2
    ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  printf '%s\n' "curl is required to download the official bws installer." >&2
  exit 2
fi

installer="$(mktemp "${TMPDIR:-/tmp}/install-bws.XXXXXX")"

cleanup() {
  rm -f "$installer"
}

trap cleanup EXIT HUP INT TERM

printf '%s\n' "bws is missing. Downloading the official Bitwarden installer."
curl -fsSL https://bws.bitwarden.com/install -o "$installer"
sh "$installer"

if command -v bws >/dev/null 2>&1; then
  bws --version
  exit 0
fi

if [ -x "${HOME}/.local/bin/bws" ]; then
  "${HOME}/.local/bin/bws" --version
  printf '%s\n' "Add ${HOME}/.local/bin to PATH before continuing." >&2
  exit 2
fi

printf '%s\n' "The official installer completed, but bws was not found." >&2
exit 1
