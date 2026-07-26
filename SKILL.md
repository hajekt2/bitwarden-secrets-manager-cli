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
4. Run authenticated commands through `scripts/with-bws-token.sh`.
   It uses an existing `BWS_ACCESS_TOKEN` first.
   On Linux, when the variable is absent, it tries the user keyring entry identified by `service bws account access-token`.
5. If neither source provides a token, ask the user to inject it securely.
   On an Ubuntu user session, guide the user through the Linux keyring setup in [references/cli-guide.md](references/cli-guide.md).
   Do not ask the user to paste the token into chat.
6. Run `scripts/check-auth.sh` to perform a read-only authentication check that emits no vault data.

Read [references/cli-guide.md](references/cli-guide.md) for command syntax, output behavior, configuration, and troubleshooting.
Use the live `bws <command> --help` output and linked official Bitwarden documentation as the final authority.

## Protect credentials and secret values

- Never print, repeat, summarize, or commit an access token or secret value.
- Never place an access token directly in a command line with `--access-token`.
  Command arguments can appear in shell history, process listings, logs, and agent traces.
- Prefer runtime secret injection or an already-set `BWS_ACCESS_TOKEN`.
  If secure injection is unavailable, ask the user to export it in their own shell and confirm when ready.
- On Linux user sessions, prefer the keyring entry `service bws account access-token`.
  Retrieve it through `scripts/with-bws-token.sh` or capture it without printing:

  ```bash
  export BWS_ACCESS_TOKEN="$(secret-tool lookup service bws account access-token)"
  ```

- Disable shell tracing before retrieving credentials.
  Never run `echo "$BWS_ACCESS_TOKEN"` or otherwise verify a token by printing it.
- Do not assume `secret-tool` works for a pure system service or a headless session without an available and unlocked keyring.
- Do not create `.env` files unless the user explicitly asks.
  If one is required, keep it outside version control, restrict permissions, and verify that Git ignores it.
- Do not expose raw `bws secret list` or `bws secret get` JSON in logs because both include secret values.
- Use `scripts/list-secret-metadata.sh [PROJECT_ID]` when only IDs and keys are needed.
- Prefer a purpose-built single-secret helper over `bws run`.
  `bws run` exposes every secret in the selected project to a shell and is an advanced, high-risk operation.
- Use `--output none` for mutations unless returned metadata is required.

If a token appears in conversation or tool output, do not echo it.
Recommend rotation if it was exposed in a durable or public location.

## Work read-only first

Resolve the exact organization-visible objects before changing anything:

```bash
scripts/with-bws-token.sh bws project list --output table
scripts/list-secret-metadata.sh
scripts/list-secret-metadata.sh "$PROJECT_ID"
```

Listing projects does not expose secret values.
The metadata helper deliberately removes each secret's value and note before printing.

For a specific value, retrieve it by UUID and avoid rendering it:

```bash
task_secret_value="$(
  scripts/with-bws-token.sh bws secret get "$SECRET_ID" --output json |
    jq -er '.value | select(type == "string" and length > 0)'
)"
trap 'unset task_secret_value' EXIT HUP INT TERM
printf '%s' "$task_secret_value" | trusted-command-reading-stdin
unset task_secret_value
trap - EXIT HUP INT TERM
```

Do not run the example unchanged.
Adapt it so the trusted destination consumes the variable, and ensure shell tracing is disabled.
Do not pass the value as a command argument.

For Vercel, use the bundled single-secret synchronizer:

```bash
scripts/sync-secret-to-vercel.py \
  "$SECRET_ID" \
  RESEND_API_KEY \
  production
```

The helper retrieves exactly one secret by UUID, validates it in process memory, passes it to `vercel env add` through standard input, suppresses child output, and reports only the variable name and target.
Add `--git-branch BRANCH` only for a branch-scoped Preview variable.

## Advanced: run a process with project secrets

Treat `bws run` as an exceptional, high-risk operation.
It does not preserve an argument vector.
It joins the supplied arguments into one string and executes that string through a shell.
Quoting that looks safe at the calling shell can therefore be lost or reinterpreted.

Never call `bws run` directly from an agent operation.
Use the guarded wrapper:

```bash
scripts/safe-bws-run.sh "$PROJECT_ID" vercel deploy
```

The wrapper always uses `--no-inherit-env`, resolves the executable before launching `bws`, restricts commands to a narrow allowlist, and accepts only shell-safe argument tokens.
It rejects shells, interpreters, environment-dump commands, `-c` command strings, whitespace, control characters, and shell metacharacters.
Do not bypass the wrapper with nested `sh -c`, `bash -c`, PowerShell command strings, semicolons, newlines, command substitutions, `set`, `env`, `printenv`, or `export -p`.

`--no-inherit-env` reduces exposure of unrelated credentials but is not a sandbox.
The child still receives every accessible secret in the selected project.
Use the single-secret path whenever the destination needs only one value.

## Change projects or secrets

Before create, edit, or delete operations:

1. Confirm the exact project or secret ID and intended new state.
2. Verify the access token has the required machine-account scope.
3. Keep values in environment variables or another secure runtime channel.
4. Use `--output none` unless non-secret response metadata is needed.
5. Re-read metadata after the change and report only IDs, keys, and status.

Examples:

```bash
scripts/with-bws-token.sh bws project create "$PROJECT_NAME" --output none
scripts/with-bws-token.sh bws project edit "$PROJECT_ID" --name "$NEW_NAME" --output none
scripts/with-bws-token.sh bws secret create "$SECRET_KEY" "$SECRET_VALUE" "$PROJECT_ID" --output none
scripts/with-bws-token.sh bws secret edit "$SECRET_ID" --value "$SECRET_VALUE" --output none
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
