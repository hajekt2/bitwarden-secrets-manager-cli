# Generated provisioning

Use only after the user approves the destination and creation. This operation
creates one new vault secret whose value is a JSON object of internally generated
random hex strings. It cannot import existing credentials or inject them into an
application. Those need separately reviewed, destination-bound operations.

Run each target from one designated provisioning host. The API has no global
name uniqueness or idempotency guarantee; another host is not protected by this
host's lock. The designated host for a target must not change without operator
reconciliation and transfer of its non-secret receipt.

## Setup

Install the official SDK in the fixed interpreter location:

```bash
python3 -m venv "$HOME/.local/share/bws-operations/venv"
"$HOME/.local/share/bws-operations/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-provision.txt
```

The pinned dependency versions and reviewed Linux x86_64 wheel hashes are in
`requirements-provision.txt`. The installer ignores caller pip configuration.
For enforced isolation, the operator must own and protect the interpreter,
installed dependencies and requirements file as well as the worker. The worker
runs with Python isolated mode and a minimal environment. It ignores caller
Python paths, proxy variables, SDK logging options and server overrides. SDK
endpoints are the built-in Bitwarden US or EU endpoints selected by the recipe.

An operator configures `~/.config/bws-operations/recipes.json`, owned by the
operating user and mode 0600. The final file must not be a symlink. Example with
non-secret placeholder IDs:

```json
{
  "example-bootstrap": {
    "project_id": "11111111-2222-3333-4444-555555555555",
    "project_name": "example",
    "secret_name": "example-bootstrap-v1",
    "region": "us",
    "fields": {"DATABASE_PASSWORD": 32, "SECRET_KEY_BASE": 64}
  }
}
```

Field sizes are bytes of randomness, either 32 or 64. Hex strings are twice that
length. The project must already exist and its name must match. The SDK project
response supplies the organization ID; the caller cannot override it.

Run `scripts/with-bws-token.sh provision-generated example-bootstrap` only after
approving the actual recipe. Do not place credentials in arguments or recipes.

## Data boundary

The worker obtains the access token internally from the Linux keyring, generates
values in memory and calls the SDK directly. Values never enter process arguments,
the parent environment, a temporary file, or the parent interpreter. No SDK
authentication state file is requested. Worker stdout/stderr go to `/dev/null`,
including native library output. An independent pipe carries only status and a
UUID, which the parent validates before rendering. Core dumps are disabled and
the worker sets Linux `PR_SET_DUMPABLE=0` before credential access.

The SDK identifiers endpoint is used internally to refuse an existing secret
name. It returns identifiers, not secret values. This is not the raw CLI
`bws secret list` operation. Existing-secret get, sync, update, delete and generic
command execution are not part of provisioning.

These protections reduce accidental disclosure. They do not prevent root,
malicious same-user code replacement, a compromised dependency, or another route
around an unrestricted host. For enforced protection from an agent, use the
[isolated deployment boundary](cli-guide.md#enforced-deployment), including
operator-owned code, bindings, dependencies and token storage. This repository
does not install that boundary or claim secrets cannot leak under all threats.

## Retries and partial failure

The worker locks a mode-0600 receipt in `~/.local/state/bws-operations/`, keyed by
region, project and secret name so recipe aliases share the lock. It records
`pending` and fsyncs it before calling create. On confirmed success it records the
returned ID. Receipt data contains bindings and status, never a generated value.
An identical retry returns `recorded` without creating another secret. Changed
bindings and pending/corrupt receipts fail closed.

On timeout, crash, or a pending receipt, an operator must reconcile the remote
write. Do not delete receipts, rename recipes, or blindly retry. The API does not
guarantee name uniqueness. Run each recipe from one provisioning host; local
locking cannot serialize another host. An existing name is a conflict, not
permission to retrieve, adopt, overwrite, or rotate it.

Reconcile in the operator's own Bitwarden web session, outside the agent: locate
the exact project and item name and inspect item creation metadata without
revealing/copying its value. Keep the pending receipt until the outcome is
established. There is deliberately no automated reset/adopt operation. If the
outcome cannot be established, leave provisioning blocked. A successful item
should be recorded by an operator using its ID and the existing receipt binding;
an absent item needs an explicit operator decision before a new attempt.

`recorded` is evidence of a previous local success. It is not a live remote
existence check. Keep the receipt with operational records.

## Verification

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` before
publishing. Tests use synthetic values, including failures carrying secret-like
strings, and do not access the keyring or Bitwarden.

Official SDK interface: [Bitwarden Python client](https://github.com/bitwarden/sdk-sm/blob/main/languages/python/bitwarden_sdk/bitwarden_client.py).
