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
For unattended hosts, either use an operator-managed unlock mechanism for the
keyring, or declare the environment source below. The Linux keyring remains the
default credential source and is preferred when a human can unlock it.

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

## Explicit environment source

An operator declares an inherited token as the credential source:

```text
BWS_ACCESS_TOKEN_SOURCE=environment
BWS_ACCESS_TOKEN=<operator-supplied machine-account token>
```

The declaration is authoritative: it selects the inherited token even on a host
where `/usr/bin/secret-tool` is executable. Use it for containers without
keyring support and for hosts that must work unattended after a reboot, where an
interactive keyring password is unavailable.

Load both values from an operator-owned store with owner-only permissions, for
example a `0600` file under `~/.config/` sourced by the session manager, or a
systemd user unit using `LoadCredential=`. Do not type or print the token in an
agent command, chat, log, shell profile, or committed file. Keep the store out of
version control and out of any directory the task writes to.

The wrapper reads the inherited value without copying it into parent `os.environ`.
The fixed `bws` child receives a minimal environment containing the token; fixed
SDK workers receive it through a private pipe or stdin. Unrelated inherited
variables are excluded, and no token is returned.

This mode is still fail closed. Without the exact source declaration, an inherited
token is refused on every host, so an accidental or agent-supplied
`BWS_ACCESS_TOKEN` never becomes the credential by itself.

Understand the residual exposure before choosing this mode. The token is then
present in the agent's own process environment and in `/proc/<pid>/environ` for
that user, so a plain `env` or `printenv` in a tool call writes it into the
transcript. The wrapper excludes `BWS_*` from the application environment and
sets `RLIMIT_CORE` to zero, but it cannot stop the agent from reading its own
environment. Prefer a narrowly scoped machine account, a token expiry, and a
command guardrail that blocks environment dumps.

Without a declaration, a host with an installed but locked, misconfigured, or
unreachable keyring must repair the keyring rather than silently fall back to the
environment source.

Use `secret-names us` for Bitwarden cloud US or `secret-names eu` for Bitwarden
cloud EU. It uses `bws project list` only for project identifiers and the pinned
SDK's identifier-only secret listing endpoint for keys. It never invokes the raw
bulk `bws secret list` command or fetches a value. Output contains project and key
names. A project ID appears only when duplicate project names need disambiguation.
The result includes `count`, the number of identifiers the listing returned, so
completeness is self-checking: a secret whose project is not listed appears under
an `unattributed:` marker instead of being omitted, and a failed or partial
listing exits nonzero rather than returning a shortened list.

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

- Direct raw `secret list` and `secret get` calls through the wrapper are rejected.
  The `run --secret ENV=UUID -- COMMAND` operation fetches selected values internally
  and injects them into any agent-selected command without recipe or hash approval.
- `list-secret-metadata.sh` is disabled because its implementation fetched all values.
- The old `safe-bws-run.sh` interface remains disabled. Use the direct `run`
  operation instead; it accepts arbitrary commands and suppresses their output.
- `sync-secret-to-vercel.py` is disabled until an operation binds an approved
  secret to an approved destination outside agent control.
- An inherited `BWS_ACCESS_TOKEN` is refused unless the operator declares
  `BWS_ACCESS_TOKEN_SOURCE=environment`. Shell, container, and CI integrations set
  both values in the operator-owned environment; they must not rely on an
  undeclared token.

## Official references

- [Bitwarden Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/)
- [Access tokens and machine-account scope](https://bitwarden.com/help/access-tokens/)
- [Local decryption process](https://bitwarden.com/help/secret-decryption/)
- [Systemd service credentials](https://systemd.io/CREDENTIALS/)
