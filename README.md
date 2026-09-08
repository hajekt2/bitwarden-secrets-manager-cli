# Bitwarden Secrets Manager CLI skill

An Agent Skill for performing approved Bitwarden operations without returning
credentials to the agent. `bws` is the Secrets Manager CLI, separate from the
`bw` Password Manager CLI.

## Install

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli -g
```

The bundled operation helper supports Linux with Python 3. It uses the user
keyring by default and has an explicit fail-closed container environment mode.
See [operator setup](references/cli-guide.md).

## Supported operations

```bash
scripts/check-auth.sh
scripts/with-bws-token.sh projects
scripts/with-bws-token.sh secret-names REGION
scripts/with-bws-token.sh provision-generated RECIPE
scripts/with-bws-token.sh run-approved RECIPE
```

Authentication returns a fixed status. Project listing returns only IDs and
names as JSON. Secret-name listing uses the SDK identifier-only endpoint and
returns project and key names, never values. The token is loaded internally from
the Linux keyring by default. A host without executable keyring support can opt in
to its already-present environment token with `BWS_ACCESS_TOKEN_SOURCE=environment`.
Keyring-capable hosts still reject an inherited `BWS_ACCESS_TOKEN`.

Generated provisioning uses the pinned official Python SDK in a separate worker,
not `bws secret create`, whose value argument would expose plaintext in process
arguments. It accepts an approved recipe and returns a receipt ID, never values.
See [setup and retry rules](references/provisioning.md). It does not import or
export existing secrets and does not install an isolated credential service.

Approved operations can consume selected secrets and import signing material.
They execute hash-pinned reviewed scripts, pass credentials through stdin, suppress
all raw child output, and return only status and imported secret IDs. See
[operation bindings and retry rules](references/approved-operations.md).

The wrapper is no longer a general command launcher. Raw secret listing,
secret retrieval, arbitrary commands, and `bws run` are rejected before keyring
access. Former metadata-listing, generic injection, and arbitrary Vercel sync
helpers remain as compatibility entry points that fail closed.

To add secret-consuming work, implement a named operation with an approved
secret and destination binding. Fetch credentials inside its private worker, pass them
only to the intended child, and return selected results or fixed status. Do not
provide an API that returns a key or accepts an arbitrary command.

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
command rejection, strict keyring-host behavior, explicit container opt-in,
child environment isolation, identifier-only enumeration, response selection,
and failures/timeouts. They do not prove host isolation.

## Files

- [SKILL.md](SKILL.md): agent workflow and restrictions.
- [scripts/bws-operations.py](scripts/bws-operations.py): fixed operation dispatcher.
- [scripts/with-bws-token.sh](scripts/with-bws-token.sh): isolated-Python entry point.
- [scripts/check-auth.sh](scripts/check-auth.sh): authentication check.
- [references/cli-guide.md](references/cli-guide.md): operator setup and deployment requirements.

## License

[MIT](LICENSE)
