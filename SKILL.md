---
name: bitwarden-secrets-manager-cli
description: Check Bitwarden access, create generated secrets, and inject selected secrets into scripts or commands. Use for bws and Bitwarden-backed tasks without displaying credentials.
---

# Bitwarden Secrets Manager

Use secrets for the authorized task without displaying their values. The agent
may choose or create any script or command that consumes application secrets.
No script allowlist, named recipe, hash pin, version pin, or separate script
approval is required. Authorization for the actual task still controls external
writes and destructive actions.

## Inject secrets into a command

Use the bundled Linux wrapper:

```bash
scripts/with-bws-token.sh run --secret API_TOKEN=11111111-2222-3333-4444-555555555555 -- python3 /absolute/path/task.py
```

Replace the example UUID with the required secret ID. Repeat `--secret ENV=UUID`
for each required credential. The wrapper fetches only those secrets and puts
their values in the command's environment. It accepts any executable and arguments,
including an interpreter and an agent-created script. Run from the task's working
directory, using the wrapper's absolute path when needed.

The command inherits the caller's environment except `BWS_*` variables. The
Bitwarden machine-account token goes only to the internal `bws` requests, never
to the application command. The token comes from the Linux keyring under
`service bws account access-token`, or from an operator-declared environment
credential.

The wrapper discards command stdout and stderr, including failures. It returns
only a fixed completion status. The default timeout is 300 seconds; set
`--timeout SECONDS` before `--` for longer tasks. It terminates the command's
process group when execution ends. Use foreground commands, not service launchers.

Read application credentials from environment variables inside the script.
Keep credentials out of arguments, tool responses, chat, logs, and temporary
files. Write credentials only to runtime destinations required by the task,
with appropriate access controls. Verify completion through non-secret results.
A failed or timed-out command can have made partial writes; inspect the task's
state before retrying.

## Other operations

```bash
scripts/with-bws-token.sh check-auth
scripts/with-bws-token.sh projects
scripts/with-bws-token.sh secret-names REGION
```

`check-auth` returns a fixed read-only status. `projects` returns project IDs and
names. `secret-names us` or `secret-names eu` returns secret key names and
project names through the SDK identifier-only endpoint, without values.

The keyring is the default credential source. An operator selects an inherited
token instead by declaring `BWS_ACCESS_TOKEN_SOURCE=environment`; the declaration
is authoritative on any host. Without that exact declaration an inherited
non-empty `BWS_ACCESS_TOKEN` is refused. The token is still excluded from the
application environment. If no credential source resolves, ask the user to repair
it in their own session, never to paste credentials.
See [operator setup](references/cli-guide.md).

Existing `provision-generated RECIPE`, `run-approved RECIPE`, and
`inspect-approved RECIPE` remain available for workflows that use recipes.
Their recipe validation applies only to those legacy operations, not to `run`.
See [generated provisioning](references/provisioning.md) and
[recipe operations](references/approved-operations.md) when using them.

`run-approved` also supports the existing repeatable `opentofu-state-inventory-v1`
result contract. Its validation and private result-file cleanup remain unchanged.

## Boundary

This wrapper prevents accidental output disclosure. It does not sandbox scripts
or an agent running as the same OS user. The selected command can access its
injected secrets, write them, or send them over the network. Choose commands and
secret scope according to the authorized task. Raw secret output through `bws
secret get`, bulk `bws secret list`, or environment dumps exposes credentials to
the agent; use the wrapper for credential injection.

An isolated credential service is optional when stronger protection against the
agent itself is required. See [isolation requirements](references/cli-guide.md#enforced-deployment).
