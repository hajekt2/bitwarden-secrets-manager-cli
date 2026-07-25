#!/bin/sh

set -eu

if [ "$#" -eq 0 ]; then
  printf '%s\n' "Usage: $0 COMMAND [ARG ...]" >&2
  exit 2
fi

if [ -n "${BWS_ACCESS_TOKEN:-}" ]; then
  exec "$@"
fi

if [ "$(uname -s 2>/dev/null || true)" = "Linux" ] &&
  command -v secret-tool >/dev/null 2>&1; then
  keyring_token="$(secret-tool lookup service bws account access-token 2>/dev/null || true)"

  if [ -n "$keyring_token" ]; then
    BWS_ACCESS_TOKEN="$keyring_token"
    export BWS_ACCESS_TOKEN
    unset keyring_token
    exec "$@"
  fi
fi

printf '%s\n' \
  "No Bitwarden Secrets Manager access token is available." \
  "Set BWS_ACCESS_TOKEN through a secure environment, or use an Ubuntu user keyring:" \
  "  sudo apt install libsecret-tools gnome-keyring" \
  "  secret-tool store --label=\"Bitwarden Secrets Manager\" service bws account access-token" \
  "Then retry without pasting or printing the token." >&2
exit 2
