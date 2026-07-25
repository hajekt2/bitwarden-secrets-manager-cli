---
name: bitwarden-secrets-manager-cli
description: Operate Bitwarden Secrets Manager through the `bws` CLI, including installing the CLI when missing, authenticating with machine-account access tokens, configuring US, EU, or self-hosted servers, listing and managing projects and secrets, and injecting secrets into trusted processes. Use for requests involving Bitwarden Secrets Manager, `bws`, `BWS_ACCESS_TOKEN`, machine accounts, secret retrieval, secret injection, or Secrets Manager automation and CI/CD.
---

# Bitwarden Secrets Manager CLI

Use `bws` with secret-safe defaults.
Install it when missing, authenticate without exposing the access token, inspect read-only state first, and make mutations only when the requested scope is exact.

## Start every task

1. Run `scripts/ensure-bws.sh`.
   On native Windows without a POSIX shell, use the official PowerShell installer documented in [references/cli-guide.md](references/cli-guide.md).
2. Run `bws --version` and `bws --help` when command behavior may vary by version.
3. Determine the server before authenticating.
   Bitwarden US is the default.
   Configure EU or self-hosted deployments only when the user identifies that environment.
4. Use an existing `BWS_ACCESS_TOKEN` environment variable.
   If none exists, ask the user to inject or export the token in their own secure environment.
5. Run `scripts/check-auth.sh` to perform a read-only authentication check that emits no vault data.

Read [references/cli-guide.md](references/cli-guide.md) for command syntax, output behavior, configuration, and troubleshooting.
Use the live `bws <command> --help` output and linked official Bitwarden documentation as the final authority.

## Protect credentials and secret values

- Never print, repeat, summarize, or commit an access token or secret value.
- Never place an access token directly in a command line with `--access-token`.
  Command arguments can appear in shell history, process listings, logs, and agent traces.
- Prefer runtime secret injection or an already-set `BWS_ACCESS_TOKEN`.
  If secure injection is unavailable, ask the user to export it in their own shell and confirm when ready.
- Do not create `.env` files unless the user explicitly asks.
  If one is required, keep it outside version control, restrict permissions, and verify that Git ignores it.
- Do not expose raw `bws secret list` or `bws secret get` JSON in logs because both include secret values.
- Use `scripts/list-secret-metadata.sh [PROJECT_ID]` when only IDs and keys are needed.
- Prefer `bws run` to pass values directly to a trusted process instead of retrieving and displaying them.
- Use `--output none` for mutations unless returned metadata is required.

If a token appears in conversation or tool output, do not echo it.
Recommend rotation if it was exposed in a durable or public location.

## Work read-only first

Resolve the exact organization-visible objects before changing anything:

```bash
bws project list --output table
scripts/list-secret-metadata.sh
scripts/list-secret-metadata.sh "$PROJECT_ID"
```

Listing projects does not expose secret values.
The metadata helper deliberately removes each secret's value and note before printing.

For a specific value, avoid rendering it:

```bash
SECRET_VALUE="$(bws secret get "$SECRET_ID" --output json | jq -r '.value')"
export SECRET_VALUE
trusted-command-reading-env
unset SECRET_VALUE
```

Do not run the example unchanged.
Adapt it so the trusted destination consumes the variable, and ensure shell tracing is disabled.

## Inject secrets into a trusted process

Use `bws run` when secret keys are valid environment-variable names:

```bash
bws run --project-id "$PROJECT_ID" -- trusted-command
```

Use `--no-inherit-env` when the child should receive a minimal inherited environment:

```bash
bws run --project-id "$PROJECT_ID" --no-inherit-env -- trusted-command
```

Treat `--no-inherit-env` as environment cleanup, not a sandbox.
Execute only binaries and scripts the user trusts because the child process receives the secrets.
Use `--uuids-as-keynames` when secret names are not POSIX-compatible or may collide.

## Change projects or secrets

Before create, edit, or delete operations:

1. Confirm the exact project or secret ID and intended new state.
2. Verify the access token has the required machine-account scope.
3. Keep values in environment variables or another secure runtime channel.
4. Use `--output none` unless non-secret response metadata is needed.
5. Re-read metadata after the change and report only IDs, keys, and status.

Examples:

```bash
bws project create "$PROJECT_NAME" --output none
bws project edit "$PROJECT_ID" --name "$NEW_NAME" --output none
bws secret create "$SECRET_KEY" "$SECRET_VALUE" "$PROJECT_ID" --output none
bws secret edit "$SECRET_ID" --value "$SECRET_VALUE" --output none
```

Deletion is destructive.
Require explicit user authorization for the resolved IDs immediately before running `bws secret delete` or `bws project delete`.

## Configure another Bitwarden server

For Bitwarden EU:

```bash
bws config server-base https://vault.bitwarden.eu
```

For self-hosted Bitwarden, use the base URL supplied by the user:

```bash
bws config server-base "$BITWARDEN_BASE_URL"
```

Prefer `BWS_SERVER_URL`, `BWS_PROFILE`, or a task-specific config file when the configuration should be temporary or isolated.
Do not overwrite an existing default profile without checking it first.
