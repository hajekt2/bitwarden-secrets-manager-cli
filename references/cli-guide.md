# `bws` CLI guide

This guide summarizes the official Bitwarden Secrets Manager CLI documentation.
Check the live sources and `bws <command> --help` before relying on version-sensitive behavior.

Official sources:

- [Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/)
- [Access tokens](https://bitwarden.com/help/access-tokens/)
- [`bws` source and releases](https://github.com/bitwarden/sdk-sm)

## Install

Bitwarden provides native binaries for Linux, macOS, and Windows.
Its official installers download a release archive and verify its SHA-256 checksum.

POSIX:

```bash
curl -fsSL https://bws.bitwarden.com/install -o /tmp/install-bws.sh
sh /tmp/install-bws.sh
```

PowerShell:

```powershell
iwr https://bws.bitwarden.com/install | iex
```

Cargo:

```bash
cargo install bws --locked
```

Docker:

```bash
docker run --rm -it ghcr.io/bitwarden/bws --help
```

The bundled `scripts/ensure-bws.sh` uses the official POSIX installer only when `bws` is not already on `PATH`.

## Authenticate

Create an access token for a Bitwarden Secrets Manager machine account.
The token can access only the projects and secrets assigned to that machine account.
Bitwarden does not retain a recoverable copy of the token after creation.

Prefer an environment variable:

```bash
export BWS_ACCESS_TOKEN='set-this-in-your-own-secure-shell'
```

Do not include the real value in documentation, committed files, shell history, process arguments, chat output, or agent tool calls.
Although `bws` supports `--access-token`, avoid it because command arguments are easier to expose.

### Linux user keyring

On Ubuntu, prefer `secret-tool` when the agent runs under an interactive user session with an available and unlocked keyring.
Install the tools when needed:

```bash
sudo apt install libsecret-tools gnome-keyring
```

Store the token using fixed lookup attributes:

```bash
secret-tool store \
  --label="Bitwarden Secrets Manager" \
  service bws \
  account access-token
```

The command prompts for the secret value.
The user should enter it directly in their own terminal.
Do not pass the token through standard command arguments, chat, or agent output.

Retrieve the token into the current shell without displaying it:

```bash
set +x
export BWS_ACCESS_TOKEN="$(secret-tool lookup service bws account access-token)"
```

For agent commands, use the bundled wrapper so the token does not depend on shell state persisting between tool calls:

```bash
scripts/with-bws-token.sh bws project list --output none
```

The wrapper first uses an existing non-empty `BWS_ACCESS_TOKEN`.
If it is absent on Linux, the wrapper looks up `service bws account access-token`.
It never prints the retrieved token.

If lookup fails, confirm that the process has a user D-Bus session, the keyring is running and unlocked, and the entry was stored with the exact attributes above.
Do not use this as the default for a pure system service.
Use systemd credentials, the service manager's environment mechanism, or the deployment platform's secret store instead.

Validate authentication without printing vault data:

```bash
scripts/with-bws-token.sh bws project list --output none
```

Frequent new sessions from one IP address can be rate-limited.
The CLI stores encrypted authentication state under `~/.config/bws/state` by default to reduce repeated authentication.

## Configure a server

Bitwarden US is the default.
EU and self-hosted users must configure their server.

```bash
bws config server-base https://vault.bitwarden.eu
bws config server-base https://bitwarden.example.com
```

The default config is `~/.config/bws/config`.
Use `--profile`, `BWS_PROFILE`, `--config-file`, or `BWS_CONFIG_FILE` to isolate configurations.
Use `--server-url` or `BWS_SERVER_URL` for a per-command override.

## Outputs

Supported output formats are `json`, `yaml`, `env`, `table`, `tsv`, and `none`.
JSON is the default.

Secret `get` and `list` output includes decrypted values.
Do not print it when only IDs, keys, or status are needed.

Use:

```bash
scripts/list-secret-metadata.sh
scripts/list-secret-metadata.sh "$PROJECT_ID"
```

Use `--output none` for writes when no response body is required.
The `env` output format comments out non-POSIX key names, but it still contains secret values and must be treated as sensitive.

## Projects

```bash
scripts/with-bws-token.sh bws project list
scripts/with-bws-token.sh bws project get "$PROJECT_ID"
scripts/with-bws-token.sh bws project create "$NAME"
scripts/with-bws-token.sh bws project edit "$PROJECT_ID" --name "$NEW_NAME"
scripts/with-bws-token.sh bws project delete "$PROJECT_ID"
```

Project list and get responses contain metadata but no secret values.
Create, edit, and delete change remote state.

## Secrets

Current syntax uses `bws secret <verb>`.
Older `bws list secrets` examples are obsolete compatibility syntax.

```bash
scripts/with-bws-token.sh bws secret list
scripts/with-bws-token.sh bws secret list "$PROJECT_ID"
scripts/with-bws-token.sh bws secret get "$SECRET_ID"
scripts/with-bws-token.sh bws secret create "$KEY" "$VALUE" "$PROJECT_ID"
scripts/with-bws-token.sh bws secret edit "$SECRET_ID" --key "$KEY" --value "$VALUE" --note "$NOTE"
scripts/with-bws-token.sh bws secret delete "$SECRET_ID"
```

`secret create` requires a key, value, and project ID.
`secret edit` can change the key, value, note, or project ID.
Secret read responses contain decrypted values.
Secret values passed to create or edit are command arguments, so keep shell tracing disabled and avoid literal values in command history.

## Copy one secret to Vercel

Prefer the single-secret synchronizer when a Vercel environment variable needs one Bitwarden value:

```bash
scripts/sync-secret-to-vercel.py \
  "$SECRET_ID" \
  RESEND_API_KEY \
  production
```

The helper retrieves exactly one secret by UUID.
It validates the value in process memory and sends it to `vercel env add` through standard input.
It suppresses `bws` and Vercel child output and reports only the variable name and target.
It uses `--force` and `--yes`, so invoke it only after resolving the exact Vercel project, variable name, and target.

Use a branch-scoped Preview variable only when required:

```bash
scripts/sync-secret-to-vercel.py \
  "$SECRET_ID" \
  RESEND_API_KEY \
  preview \
  --git-branch feature/contact
```

The helper requires Python 3, `bws`, and the Vercel CLI.
Run it from the linked Vercel project directory.
It does not pass the secret through command arguments or `bws run`.

## Advanced: run a process with project secrets

`bws run` injects accessible secrets as environment variables into a child process:

```bash
scripts/safe-bws-run.sh "$PROJECT_ID" vercel deploy
```

Treat this as an exceptional, high-risk operation.
The `bws` implementation joins the command arguments into one string and executes that string through the configured shell.
It does not preserve the original argument vector.
The default shell is `sh` on Linux and macOS and PowerShell on Windows.

The guarded wrapper always sets `--no-inherit-env`, resolves the executable to an absolute path, uses a narrow executable allowlist, and rejects tokens that the shell could reinterpret.
Do not call `bws run` directly from an agent operation.
Do not use nested shells, interpreters, `-c`, command substitutions, shell control operators, `set`, `env`, `printenv`, or `export -p`.

`--no-inherit-env` reduces inherited variables but does not sandbox the child.
The child still receives every accessible secret in the selected project.
Prefer a purpose-built single-secret helper whenever the destination needs only one value.

## Troubleshoot

`Missing access token`:

- Confirm `BWS_ACCESS_TOKEN` exists in the process that launches `bws`.
- Do not print the variable while checking it.

Authorization or missing objects:

- Confirm the machine account is assigned to the project.
- Confirm its read or write permissions match the requested action.
- Remember that unassigned projects and secrets are intentionally invisible.

EU or self-hosted connection failure:

- Check the configured server base, profile, config file, and `BWS_SERVER_URL`.

Rate limits:

- Reuse encrypted CLI state.
- Avoid starting many fresh authenticated sessions from the same IP in a short period.

Unexpected syntax:

- Run `bws --version`.
- Run `bws <command> --help`.
- Prefer `bws secret <verb>` and `bws project <verb>`.
