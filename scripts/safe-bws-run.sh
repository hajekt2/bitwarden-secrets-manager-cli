#!/bin/sh

set -eu

usage() {
  printf '%s\n' "Usage: $0 PROJECT_ID COMMAND [ARG ...]" >&2
}

if [ "$#" -lt 2 ]; then
  usage
  exit 2
fi

project_id="$1"
shift

if ! printf '%s\n' "$project_id" |
  LC_ALL=C grep -Eq '^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$'; then
  printf '%s\n' "PROJECT_ID must be a UUID." >&2
  exit 2
fi

requested_command="$1"
shift
command_name="${requested_command##*/}"

case "$command_name" in
  helm | kubectl | terraform | tofu | vercel) ;;
  sh | bash | dash | zsh | fish | powershell | pwsh | cmd | \
    python | python3 | ruby | perl | node | deno | bun | \
    env | printenv | set | export)
    printf '%s\n' "Refusing shell, interpreter, or environment-dump command: $command_name" >&2
    exit 2
    ;;
  *)
    printf '%s\n' \
      "Command is not on the safe bws run allowlist: $command_name" \
      "Allowed commands: helm, kubectl, terraform, tofu, vercel" >&2
    exit 2
    ;;
esac

resolved_command="$(command -v "$requested_command" 2>/dev/null || true)"

case "$resolved_command" in
  /*) ;;
  *)
    printf '%s\n' "Could not resolve the command to an absolute executable path." >&2
    exit 2
    ;;
esac

validate_token() {
  token="$1"

  case "$token" in
    -c | --command)
      printf '%s\n' "Refusing a command-string argument: $token" >&2
      exit 2
      ;;
  esac

  if ! printf '%s\n' "$token" |
    LC_ALL=C grep -Eq '^[-A-Za-z0-9_./:@%+=,]+$'; then
    printf '%s\n' \
      "Refusing an argument containing whitespace, control characters, or shell metacharacters." >&2
    exit 2
  fi
}

validate_token "$resolved_command"

for argument in "$@"; do
  validate_token "$argument"
done

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

exec "${script_dir}/with-bws-token.sh" \
  bws run \
  --project-id "$project_id" \
  --no-inherit-env \
  -- \
  "$resolved_command" \
  "$@"
