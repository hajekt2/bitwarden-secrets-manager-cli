#!/bin/sh

set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
"${script_dir}/ensure-bws.sh" >/dev/null

if "${script_dir}/with-bws-token.sh" bws project list --output none; then
  printf '%s\n' "bws authentication succeeded with a read-only project check."
  exit 0
fi

printf '%s\n' "bws authentication failed. Check token scope, server, and profile settings." >&2
exit 1
