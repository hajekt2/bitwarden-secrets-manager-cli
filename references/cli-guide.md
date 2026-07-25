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

Validate authentication without printing vault data:

```bash
bws project list --output none
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
bws project list
bws project get "$PROJECT_ID"
bws project create "$NAME"
bws project edit "$PROJECT_ID" --name "$NEW_NAME"
bws project delete "$PROJECT_ID"
```

Project list and get responses contain metadata but no secret values.
Create, edit, and delete change remote state.

## Secrets

Current syntax uses `bws secret <verb>`.
Older `bws list secrets` examples are obsolete compatibility syntax.

```bash
bws secret list
bws secret list "$PROJECT_ID"
bws secret get "$SECRET_ID"
bws secret create "$KEY" "$VALUE" "$PROJECT_ID"
bws secret edit "$SECRET_ID" --key "$KEY" --value "$VALUE" --note "$NOTE"
bws secret delete "$SECRET_ID"
```

`secret create` requires a key, value, and project ID.
`secret edit` can change the key, value, note, or project ID.
Secret read responses contain decrypted values.
Secret values passed to create or edit are command arguments, so keep shell tracing disabled and avoid literal values in command history.

## Run a process with secrets

`bws run` injects accessible secrets as environment variables into a child process:

```bash
bws run --project-id "$PROJECT_ID" -- trusted-command
bws run --project-id "$PROJECT_ID" --no-inherit-env -- trusted-command
bws run --project-id "$PROJECT_ID" --uuids-as-keynames -- trusted-command
```

The default shell is `sh` on Linux and macOS and PowerShell on Windows.
`--no-inherit-env` reduces inherited variables but does not sandbox the child.
Run only trusted code.
Secret names that are invalid environment-variable names may be inaccessible to POSIX tools.
`--uuids-as-keynames` converts secret IDs to safe environment-variable names.

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
