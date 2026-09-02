# Bitwarden Secrets Manager CLI skill

An Agent Skill for performing approved Bitwarden operations without returning
credentials to the agent. `bws` is the Secrets Manager CLI, separate from the
`bw` Password Manager CLI.

## Install

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli -g
```

The bundled operation helper currently supports Linux with Python 3 and an
available user keyring. See [operator setup](references/cli-guide.md).

## Supported operations

```bash
scripts/check-auth.sh
scripts/with-bws-token.sh projects
```

Authentication returns a fixed status. Project listing returns only IDs and
names as JSON. The token is loaded internally from the Linux keyring and supplied
only to the fixed `bws` child. An inherited `BWS_ACCESS_TOKEN` is rejected.

The wrapper is no longer a general command launcher. Raw secret listing,
secret retrieval, arbitrary commands, and `bws run` are rejected before keyring
access. Former metadata-listing, generic injection, and arbitrary Vercel sync
helpers remain as compatibility entry points that fail closed.

To add secret-consuming work, implement a named operation with an approved
secret and destination binding. Fetch credentials inside its service, pass them
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
