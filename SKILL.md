---
name: bitwarden-secrets-manager-cli
description: Check Bitwarden access, create generated secrets, and run approved credential-consuming operations without returning values. Use for bws, Bitwarden-backed deployment, signing-key import, or OpenTofu state inventory.
---

# Bitwarden Secrets Manager

Request work, never credentials. Return only the approved operation's result.
Do not print or return tokens or secret values through stdout, stderr, errors,
logs, tool responses, chat, or temporary files. Fixed deployment operations may
write credentials to their approved, access-controlled runtime destinations;
never inspect or render those files through an agent tool.

## Available operations

Use the bundled operation wrapper on Linux:

```bash
scripts/with-bws-token.sh check-auth
scripts/with-bws-token.sh projects
scripts/with-bws-token.sh secret-names REGION
```

- `check-auth` makes a read-only project request and returns a fixed status.
- `projects` returns only project IDs and names as JSON.
- `secret-names` accepts only `us` or `eu` as `REGION`. It returns a JSON object
  with `count` (the number of secret identifiers the listing returned) and
  `secrets`: each secret key name and project name, sorted. A project ID is
  included only when duplicate project names require disambiguation. A secret
  whose project is not among the listed projects, or that has no project, is
  reported under an `unattributed:` marker with the project ID (or
  `unattributed:no-project`) instead of being dropped, so a complete listing
  with unattributable entries is visibly distinct from a failed or partial one;
  a failed listing exits nonzero without output.

`secret-names` first selects project identifiers, then calls the pinned SDK's
identifier-only `client.secrets().list(organization_id)` endpoint. It never
invokes `bws secret list` and never calls `client.secrets().get`. The region is
explicit because the SDK client uses fixed Bitwarden US or EU endpoints.
- `scripts/check-auth.sh` is an alias for the authentication operation.

### Create generated secrets

After explicit user authorization, use:

```bash
scripts/with-bws-token.sh provision-generated RECIPE
```

Read [generated provisioning](references/provisioning.md) before configuring or
running it. The recipe binds an existing project, a new secret name, region,
and generated JSON fields. It accepts no secret value, arbitrary command, URL,
or output destination. Successful output contains only status and the secret ID.
It neither reads existing secret values nor imports credentials from files.
Do not put secrets in a recipe.

### Run a credential-consuming operation

After user authorization for the actual task, use:

```bash
scripts/with-bws-token.sh run-approved RECIPE
```

Read [approved operations](references/approved-operations.md) before configuring
or running one. Review the self-contained script, its fixed destinations and
every secret-bearing path. Bind its hash, input secret IDs and optional vault
import destinations in private non-secret configuration. The wrapper executes
only those reviewed bytes, supplies values through stdin, and returns only fixed
status and imported secret IDs. The caller cannot supply commands or values.

Use `scripts/with-bws-token.sh inspect-approved RECIPE` to check input bindings
without retrieving values or executing the script. It returns each configured
alias and matching secret UUIDs from the SDK identifier-only endpoint. Empty or
multiple matches require correcting the non-secret binding before execution.

Treat a failed/uncertain write as requiring operator reconciliation. Do not
delete its receipt or repeat it under another recipe name. A `recorded` result
means a previous success was recorded locally, not that the secret was fetched
or checked remotely. Never use this operation for rotation or replacement.

Use `opentofu-state-inventory-v1` only for a reviewed, repeatable OpenTofu state
inventory. It returns validated resource addresses and their count. Follow the
exact script and recipe contract in
[approved operations](references/approved-operations.md).

The wrapper rejects other operations before reading the keyring. It accepts
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
- Never add `BWS_ACCESS_TOKEN` to an agent, parent shell, shell profile, or
  global environment. A keyring-capable host rejects an inherited non-empty
  token, including when environment-token mode was requested.
- Never use the old `list-secret-metadata.sh`, `safe-bws-run.sh`, or
  `sync-secret-to-vercel.py` interfaces. They fail closed without credential lookup.
  The old Vercel interface accepted arbitrary secret IDs and destinations.

## Credential handling

The default credential source is the Linux keyring entry
`service bws account access-token`. The wrapper reads it internally with
`/usr/bin/secret-tool` and passes it only to a fixed Bitwarden CLI or SDK child.
It never writes the token to `os.environ`, arguments, logs, errors, or results.
SDK workers receive an opted-in environment token through a private inherited
file descriptor or stdin, never their environment.

On a container host where `/usr/bin/secret-tool` is not executable, an operator
may explicitly set `BWS_ACCESS_TOKEN_SOURCE=environment` in the same protected
container configuration that supplies `BWS_ACCESS_TOKEN`. Both are required.
This is not a fallback: if `secret-tool` is executable, any inherited token is
still refused. Do not enable this mode on a desktop or use it to work around a
locked or failing keyring. See [operator setup](references/cli-guide.md).

`bws` is resolved from known installation locations, not the caller's PATH.
The child environment excludes unrelated credentials and runtime/config overrides.
The wrapper captures child output, suppresses raw failure details, and returns
only the selected operation result. No arbitrary child output is forwarded.

Failures distinguish an unavailable credential source from a vault request that
failed after a credential was found. Neither case includes child output. On a
keyring host, ask the user to unlock the keyring in their own session. Do not ask
for the token or keyring password in chat.

## Enforcement boundary

These helpers restrict their own interface. They do not sandbox the agent.
A same-user process with unrestricted shell access can bypass them by reading
the keyring, running raw `bws`, modifying a helper/config/binary, or calling the
Bitwarden API itself. In environment-token mode, that process can also read the
inherited token directly. Removing `bws` from PATH or adding a denylist is insufficient.
Do not claim wrapper-only access is enforced in that environment.

Protection against an unrestricted or malicious agent requires a credential service outside
of the agent's OS identity or sandbox. The agent must lack access to the token,
keyring and D-Bus session, service environment and memory, binaries, writable
service configuration, and alternate credential paths. It must not have sudo or
another route to assume that service identity. See
[isolation requirements](references/cli-guide.md#enforced-deployment).

Do not disable sandboxing or approvals, expose the service keyring to agents,
or change runtime restrictions to make a blocked operation work.

## Adding an operation

The wrappers prevent accidental output disclosure; they do not establish host
isolation. Use approved operations for ordinary authorized deployment and import
tasks. Do not make a separate credential service a prerequisite unless the user
requires protection against the agent itself. Keep that stronger threat model
distinct from preventing accidental exposure.

When the task needs another secret-consuming operation:

1. Resolve the requested work and approved destination without retrieving values.
2. Implement a self-contained fixed operation and review its full credential
   path. Bind its hash, secret IDs and destinations in approved configuration.
   Do not offer a generic secret or command API.
3. Fetch only required secrets internally. Pass application credentials through
   stdin or the intended child environment. Never pass the Bitwarden access token
   to the application. Avoid shells and caller-controlled executables/config.
4. Return selected non-secret results or a fixed status. Suppress raw child output
   on success, failure, and timeout unless its schema is explicitly safe. String
   replacement alone is not a reliable filter for encoded or transformed secrets.
5. Test rejection and failure paths with synthetic credentials, then verify the
   approved result without rendering credentials. Require explicit authorization
   for external writes and destructive actions.

Until that reviewed operation exists, report it as unsupported. Do not fall
back to generic retrieval, `bws run`, or a command that returns a credential.
