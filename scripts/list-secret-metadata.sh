#!/usr/bin/env bash

set -euo pipefail

if ! command -v bws >/dev/null 2>&1; then
  printf '%s\n' "bws is not installed. Run scripts/ensure-bws.sh first." >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' "jq is required to remove secret values before printing." >&2
  exit 2
fi

if [[ -z "${BWS_ACCESS_TOKEN:-}" ]]; then
  printf '%s\n' "BWS_ACCESS_TOKEN is not set." >&2
  exit 2
fi

if (( $# > 1 )); then
  printf '%s\n' "Usage: $0 [PROJECT_ID]" >&2
  exit 2
fi

args=(secret list)

if (( $# == 1 )); then
  if [[ ! "$1" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
    printf '%s\n' "PROJECT_ID must be a UUID." >&2
    exit 2
  fi
  args+=("$1")
fi

bws "${args[@]}" --output json |
  jq '[.[] | {id, key, projectId, creationDate, revisionDate}]'
