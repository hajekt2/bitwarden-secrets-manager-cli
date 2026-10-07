# Bitwarden Secrets Manager CLI skill

An Agent Skill for performing approved Bitwarden operations without returning
credentials to the agent. `bws` is the Secrets Manager CLI, separate from the
`bw` Password Manager CLI.

## Install

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli -g
```

The bundled operation helper currently supports Linux with Python 3 and either an
available user keyring or an operator-declared environment credential. See
[operator setup](references/cli-guide.md).

## Supported operations

```bash
scripts/check-auth.sh
scripts/with-bws-token.sh projects
scripts/with-bws-token.sh secret-names REGION
scripts/with-bws-token.sh provision-generated RECIPE
scripts/with-bws-token.sh run-approved RECIPE
```

Authentication returns a fixed status. Project listing returns only IDs and
names as JSON. The token is loaded internally, from the Linux keyring by default,
and supplied only to the internal `bws` child. An operator declares an inherited
token as the credential with `BWS_ACCESS_TOKEN_SOURCE=environment`; without that
declaration an inherited `BWS_ACCESS_TOKEN` is refused. Secret-name listing uses the SDK
identifier-only endpoint without retrieving values.

Generated provisioning uses the pinned official Python SDK in a separate worker,
not `bws secret create`, whose value argument would expose plaintext in process
arguments. It accepts an approved recipe and returns a receipt ID, never values.
See [setup and retry rules](references/provisioning.md). It does not import or
export existing secrets and does not install an isolated credential service.

## Run any credential-consuming script

```bash
scripts/with-bws-token.sh run --secret API_TOKEN=11111111-2222-3333-4444-555555555555 -- python3 /absolute/path/task.py
```

The agent chooses the command and binds each needed secret UUID to an environment
variable. No recipe, script allowlist, hash pin, version pin, or separate script
approval is required. Task authorization still applies to external and destructive
actions. The machine-account token is never passed to the application.

Command output is discarded and only a fixed status is returned. The default
300-second timeout can be changed with `--timeout SECONDS`. The command inherits
the caller environment except `BWS_*`. This is intended for foreground tasks;
the process group is terminated when the command ends. Arbitrary commands can
use or disclose injected credentials, so this interface is not an isolation boundary.

Legacy hash-pinned recipe operations remain available for existing workflows.
Their requirements apply only to `run-approved`, not to `run`. The existing
OpenTofu state-inventory result contract and private result cleanup are preserved.

## Security boundary

**This repository does not install an agent sandbox or isolated credential service.**
The wrappers restrict their own interface and reduce accidental disclosure.
An unrestricted agent running as the same user can still bypass them, access the
keyring, or invoke raw `bws`. A PATH shim does not fix that.

Enforced isolation requires a credential service running outside the agent's
identity/sandbox, with inaccessible credential storage and operator-owned code,
configuration, and operation bindings. The agent must have no privilege escalation
route into that service. See the [deployment requirements](references/cli-guide.md#enforced-deployment).
That stronger isolation is optional for ordinary tasks whose goal is preventing
accidental disclosure, and is not installed by the approved-operation wrapper.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n scripts/with-bws-token.sh scripts/check-auth.sh scripts/list-secret-metadata.sh scripts/safe-bws-run.sh
```

Tests use synthetic credentials and mock all credential retrieval. They cover
command rejection, inherited-token rejection, child environment isolation,
response selection, and failures/timeouts. They do not prove host isolation.

## Files

- [SKILL.md](SKILL.md): agent workflow and restrictions.
- [scripts/bws-operations.py](scripts/bws-operations.py): fixed operation dispatcher.
- [scripts/with-bws-token.sh](scripts/with-bws-token.sh): isolated-Python entry point.
- [scripts/check-auth.sh](scripts/check-auth.sh): authentication check.
- [references/cli-guide.md](references/cli-guide.md): operator setup and deployment requirements.

## License

[MIT](LICENSE)
