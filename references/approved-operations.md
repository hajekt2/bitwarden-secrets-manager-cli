# Approved credential operations

`run-approved NAME` is a same-user wrapper for preventing accidental disclosure.
It is not a security boundary against root or an agent that replaces its code.
The user must authorize the operation and its actual destinations. A recipe is
not permission to deploy, rotate or overwrite anything outside that task.

## Recipe

Store non-secret recipes in `~/.config/bws-operations/approved.json`, owned by the
current user with mode 0600. Each operation selects a reviewed, self-contained
Python script, also mode 0600, by absolute path and SHA-256. Scripts should live
in the repository that owns the actual work. The skill owns the credential wrapper.

```json
{
  "example-deploy": {
    "script": "/absolute/path/to/reviewed-operation.py",
    "sha256": "REPLACE_WITH_SCRIPT_SHA256",
    "region": "us",
    "inputs": {
      "bootstrap": {
        "secret_id": "11111111-1111-4111-8111-111111111111",
        "project_id": "22222222-2222-4222-8222-222222222222"
      }
    },
    "exports": {}
  }
}
```

The script receives a JSON object on stdin. Values are the exact selected vault
secret strings. Parse nested JSON bundles internally when necessary. It receives
no Bitwarden token and no inherited environment, credential variables, Python
hooks or proxy overrides. Its environment contains only a fixed PATH and locale.
The SDK worker reads the token from the Linux keyring by default. In the explicit
container environment mode, the wrapper transfers the already-inherited token to
that fixed worker through a private file descriptor, never through its environment
or arguments. The reviewed operation script still receives no Bitwarden token.
Use absolute executable paths and bind destination hosts, paths and accounts in
reviewed source. Use strict SSH host verification and no redirects for sensitive
HTTP requests. Credentials travel through stdin or a minimal child environment,
never arguments, URLs or log messages. Never run shell tracing or environment dumps.

An input may use `secret_name` instead of `secret_id` when its UUID is unknown.
Keep `project_id` pinned. The worker resolves the name using the SDK's
identifier-only endpoint, requires exactly one match in the pinned project, then
checks the fetched secret's project. It never retrieves values to enumerate names.
Prefer UUID bindings when already known. Ambiguous names fail before value lookup.

The script must emit exactly `{"exports": {}}` on success when no vault import
is needed. For signing-key import, configure each export as:

```json
{"signing": {"project_id": "22222222-2222-4222-8222-222222222222",
             "project_name": "example", "secret_name": "signing-v1"}}
```

Then emit `{"exports":{"signing":"SECRET_STRING_OR_SERIALIZED_JSON"}}` inside
the private worker path. The wrapper validates destination projects, rejects
existing secret names, and imports only the configured exports. Raw child output,
exceptions, HTTP responses and stderr never reach the agent. The public result
contains only `completed`/`recorded` and created secret UUIDs. Verify public keys
and deployment health separately through public/non-secret checks.

## Review and tests

Before approving the script hash, inspect all imports, subprocesses, file writes,
network destinations, exception paths and cleanup. Scripts must not load unpinned
local plugins or configuration that changes their credential destinations. Hash
pinning does not make a malicious or incomplete script safe. Changing reviewed
bytes requires a fresh review; never update the pin merely to bypass a failure.

Use synthetic credentials to test stdout/stderr leakage, failures, timeouts,
wrong project/secret IDs, altered script hashes and uncertain retries. Include the
application-specific operation in those tests, not just this generic wrapper.
Credentials may persist only at explicitly approved protected runtime destinations.

## Failure and retry

The wrapper records `pending` before invoking the operation. It runs at most once
per recorded binding on this controller. Script or import failure may have changed
the remote service; timeout may leave remote work running. Reconcile that state
before another mutation. Never delete receipts, change aliases, or change bindings
to bypass uncertainty. An operator can archive a reconciled receipt and authorize
a new execution, but the wrapper intentionally has no automatic reset command.

Successful repeated calls return `recorded` without fetching secret values or
executing the operation again. That is a local receipt, not current remote health.
Do not run the same operation from several controller machines and assume these
local receipts provide global exactly-once execution. The operation must preserve
existing data and recover partial remote work safely.

Both provisioning modes share a controller lock. Concurrent operations fail
before vault access. Child processes stay in the worker process group, which
the parent terminates on completion or timeout. Reviewed scripts must not detach
processes into separate sessions. This cleanup does not cancel remote work.
