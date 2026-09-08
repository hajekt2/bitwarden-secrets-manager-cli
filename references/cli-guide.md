# Operator setup and isolation

This reference is for human/operator setup. It does not authorize an agent to
retrieve credentials, bypass the wrapper, or relax runtime restrictions.

## Existing Linux keyring setup

An operator stores the token interactively using:

```bash
secret-tool store --label="Bitwarden Secrets Manager" service bws account access-token
```

Enter the value at the terminal prompt. Do not include it in command arguments,
chat, shell profiles, or the agent environment. In an enforced deployment,
perform this under the credential service's identity, not the agent's identity.
The keyring must be available and unlocked in that identity's session.

An ordinary desktop keyring does not guarantee unattended access after reboot.
For services, use an operator-managed unlock mechanism or a separately reviewed
service credential store. Do not solve startup by exporting the token globally.
The Linux keyring remains the default and required desktop credential source.

Use these commands to verify access without retrieving secret values:

```bash
scripts/check-auth.sh
scripts/with-bws-token.sh projects
scripts/with-bws-token.sh secret-names us
```

A source failure says that no credential source is available. A request failure
says that a credential was found but the vault request failed or rejected it.
Both suppress child stdout and stderr. Check keyring availability, machine-account
scope, and the operator-owned Bitwarden configuration. The wrapper does not accept
server or profile overrides from its caller. Existing configuration under the
operating user's home still applies; that home must be inaccessible to agents in
an enforced deployment.

## Explicit container environment source

A container that has no executable `/usr/bin/secret-tool` may use a token already
in its protected environment only when the host explicitly declares that source:

```text
BWS_ACCESS_TOKEN_SOURCE=environment
BWS_ACCESS_TOKEN=<operator-supplied machine-account token>
```

Configure both values through the container platform. Do not type or print the
token in an agent command, chat, log, shell profile, or committed file. The
wrapper reads the inherited value without copying it into parent `os.environ`.
The fixed `bws` child receives a minimal environment containing the token; fixed
SDK workers receive it through a private pipe or stdin. Unrelated inherited
variables are excluded, and no token is returned.

This mode is deliberately fail closed. Without the exact source declaration, an
inherited token is refused. If `/usr/bin/secret-tool` is executable, the inherited
token is refused even with the declaration. A host with an installed but locked,
misconfigured, or unreachable keyring must repair the keyring rather than silently
fall back to the environment source.

Use `secret-names us` for Bitwarden cloud US or `secret-names eu` for Bitwarden
cloud EU. It uses `bws project list` only for project identifiers and the pinned
SDK's identifier-only secret listing endpoint for keys. It never invokes the raw
bulk `bws secret list` command or fetches a value. Output contains project and key
names. A project ID appears only when duplicate project names need disambiguation.

## Installation

Python 3 at `/usr/bin/python3` and `bws` are required for the Linux helper.
`secret-tool` at `/usr/bin/secret-tool` is required for keyring mode. The helper
checks `~/.local/bin/bws`,
`/usr/local/bin/bws`, then `/usr/bin/bws`, without searching the caller's PATH.
`secret-names`, generated provisioning, and approved operations also require the
pinned SDK environment described in [generated provisioning](provisioning.md#setup).

`ensure-bws.sh` remains an operator installation helper using Bitwarden's official
installer. Installing raw `bws` into an unrestricted agent's account does not
provide isolation. Windows/macOS credential-service adapters are not implemented.

## Enforced deployment

The bundled scripts do not install an OS sandbox or credential service.
Before describing a deployment as enforced, an operator must establish all of:

- Separate agent and credential-service OS identities or equivalent isolation.
- No agent access to the service keyring, D-Bus/control sockets, token storage,
  home directory, process environment/memory, or secret-containing files.
- No agent write access to service code, executables, operation bindings,
  Bitwarden configuration, plugins, hooks, or child application configuration.
- No agent sudo, impersonation, container socket, debugger, host mount, or other
  route around that boundary.
- An authenticated operation API that accepts fixed operations, not arbitrary
  secret IDs, executables, arguments, URLs, or credential-export destinations.
- A scoped machine account with only the permissions required by those operations.
- Result selection and safe failure handling inside the service. Child output
  must not be forwarded merely because the command was allowlisted.

Removing an executable from PATH, putting a shell shim in front of it, or
blacklisting a command string does not prevent absolute-path execution, another
binary copy, direct API calls, or access to the keyring.

An operator should verify denied access using synthetic credentials under the
actual agent identity, then verify an approved operation. Tests of these helper
scripts alone cannot prove isolation of the host.

## Compatibility changes

- Raw `secret list` and `secret get` are rejected, even with output filtering.
- `list-secret-metadata.sh` is disabled because its implementation fetched all values.
- `safe-bws-run.sh` is disabled. Its executable-name allowlist permitted commands
  and project code that could print or send secrets elsewhere.
- `sync-secret-to-vercel.py` is disabled until an operation binds an approved
  secret to an approved destination outside agent control.
- Inherited `BWS_ACCESS_TOKEN` is rejected. Existing shell/CI integrations must
  move authentication into the credential handler. The only exception is the
  explicit container mode above on a host without executable keyring support.

## Official references

- [Bitwarden Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/)
- [Access tokens and machine-account scope](https://bitwarden.com/help/access-tokens/)
- [Local decryption process](https://bitwarden.com/help/secret-decryption/)
- [Systemd service credentials](https://systemd.io/CREDENTIALS/)
