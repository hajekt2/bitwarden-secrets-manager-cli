---
name: bitwarden-secrets-manager-cli
description: Check Bitwarden Secrets Manager access and run approved operations without returning credentials. Use for bws, machine-account access, secret injection, and Bitwarden automation. Secret listing, raw retrieval, and generic command execution are prohibited.
---

# Bitwarden Secrets Manager

Request work, never credentials. Return only the approved operation's result.
Do not print or return tokens or secret values through stdout, stderr, errors,
logs, tool responses, chat, or files readable by the agent.

## Available operations

Use the bundled operation wrapper on Linux:

```bash
scripts/with-bws-token.sh check-auth
scripts/with-bws-token.sh projects
```

- `check-auth` makes a read-only project request and returns a fixed status.
- `projects` returns only project IDs and names as JSON.
- `scripts/check-auth.sh` is an alias for the authentication operation.

The wrapper rejects all other operations before reading the keyring. It accepts
only these two exact legacy forms for compatibility:

```bash
scripts/with-bws-token.sh bws project list --output none
scripts/with-bws-token.sh bws project list --output table
```

The legacy `table` form now returns the same selected JSON metadata as `projects`.

## Prohibited paths

- Never invoke raw `bws` from an agent, including by absolute path or another interpreter.
- Reject `bws secret list`, including metadata-filtered and `--output none` forms.
  Piping a bulk secret response through `jq` still retrieves every value.
- Reject raw `bws secret get`. A helper returning one secret at a time still
  allows enumeration and exposes the value to the model.
- Reject `bws run` and arbitrary commands, shells, scripts, executable paths,
  environment dumps, config flags, and server overrides supplied to the wrapper.
- Never export `BWS_ACCESS_TOKEN` into the agent, parent shell, shell profile,
  or global environment. The wrapper rejects an inherited non-empty token.
- Never use the old `list-secret-metadata.sh`, `safe-bws-run.sh`, or
  `sync-secret-to-vercel.py` interfaces. They fail closed without credential lookup.
  The old Vercel interface accepted arbitrary secret IDs and destinations.

## Credential handling

The machine-account access token stays in the Linux keyring under
`service bws account access-token`. The wrapper reads it internally with
`/usr/bin/secret-tool` and passes it only to the fixed `bws` child environment.
It never writes it to `os.environ` or forwards it to another command.

`bws` is resolved from known installation locations, not the caller's PATH.
The child environment excludes unrelated credentials and runtime/config overrides.
The wrapper captures child output, suppresses raw failure details, and returns
only the selected operation result. No arbitrary child output is forwarded.

If the keyring is unavailable, report the failure. Ask the user to unlock it in
their own session. Do not ask for the token or keyring password in chat. See
[operator setup](references/cli-guide.md) for human-managed credential setup.

## Enforcement boundary

These helpers restrict their own interface. They do not sandbox the agent.
A same-user process with unrestricted shell access can bypass them by reading
the keyring, running raw `bws`, modifying a helper/config/binary, or calling the
Bitwarden API itself. Removing `bws` from PATH or adding a denylist is insufficient.
Do not claim wrapper-only access is enforced in that environment.

Enforced deployment requires an operator-controlled credential service outside
of the agent's OS identity or sandbox. The agent must lack access to the token,
keyring and D-Bus session, service environment and memory, binaries, writable
service configuration, and alternate credential paths. It must not have sudo or
another route to assume that service identity. See
[isolation requirements](references/cli-guide.md#enforced-deployment).

Do not disable sandboxing or approvals, expose the service keyring to agents,
or change runtime restrictions to make a blocked operation work.

## Adding an operation

When the task needs a secret-consuming operation beyond the two supported reads:

1. Resolve the requested work and approved destination without retrieving values.
2. Implement a fixed operation inside the isolated credential service. Bind its
   secret IDs, destination account/project, executable, and permitted arguments
   in operator-owned configuration. Do not offer a generic secret or command API.
3. Fetch only required secrets internally. Pass application credentials through
   stdin or the intended child environment. Never pass the Bitwarden access token
   to the application. Avoid shells and caller-controlled executables/config.
4. Return selected non-secret results or a fixed status. Suppress raw child output
   on success, failure, and timeout unless its schema is explicitly safe. String
   replacement alone is not a reliable filter for encoded or transformed secrets.
5. Test rejection and failure paths with synthetic credentials, then verify the
   approved result without rendering credentials. Require explicit authorization
   for external writes and destructive actions.

Until that operation and isolation exist, report it as unsupported. Do not fall
back to generic retrieval, `bws run`, or a command that returns a credential.
