# Bitwarden Secrets Manager CLI Skill

An Agent Skill for working safely with [Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/) through the `bws` command-line interface.

The skill helps AI coding agents install and operate `bws`, authenticate with a machine-account access token, inspect projects and secrets, inject secrets into trusted processes, and manage Secrets Manager resources without exposing sensitive values.

This repository follows the open [Agent Skills specification](https://agentskills.io) and can be installed with the [Skills CLI](https://github.com/vercel-labs/skills) into Codex, Claude Code, Cursor, and other supported agents.

> [!IMPORTANT]
> `bws` is the Bitwarden Secrets Manager CLI.
> It is separate from the `bw` CLI used with Bitwarden Password Manager.

## Install

Install the skill with the standard Skills CLI command:

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli
```

The installer detects supported agents and asks where to install the skill.
Project installation is the default.

Install it globally for use across projects:

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli -g
```

Install it globally for Codex without interactive prompts:

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli \
  --skill bitwarden-secrets-manager-cli \
  --agent codex \
  --global \
  --yes
```

List the skill without installing it:

```bash
npx skills add hajekt2/bitwarden-secrets-manager-cli --list
```

The Skills CLI requires Node.js and npm.
See the [Skills CLI documentation](https://github.com/vercel-labs/skills) for supported agents, installation scopes, and additional options.

## What the skill does

- Installs `bws` from Bitwarden's official installer when the CLI is missing.
- Supports Bitwarden US, Bitwarden EU, and self-hosted server configuration.
- Authenticates through the `BWS_ACCESS_TOKEN` environment variable.
- Validates authentication with a read-only request that prints no vault data.
- Lists secret metadata without printing secret values or notes.
- Retrieves and injects secrets without exposing them in agent output.
- Guides safe project and secret creation, editing, and deletion.
- Uses `bws run` to inject secrets directly into trusted processes.
- Uses live `bws --help` output and Bitwarden documentation as the final authority.

## Authentication

Create an access token for a [Bitwarden Secrets Manager machine account](https://bitwarden.com/help/access-tokens/).
The machine account must have access to the projects and secrets required by the task.

Provide the token as `BWS_ACCESS_TOKEN` in the environment where the agent runs.
For example, read it without echoing it in Bash:

```bash
read -rsp "BWS access token: " BWS_ACCESS_TOKEN
printf '\n'
export BWS_ACCESS_TOKEN
```

Use your shell, CI secret store, agent runtime, or another secure environment-injection mechanism to set the value.
Do not paste the token into prompts, commit it, store it in tracked `.env` files, or pass it through the `--access-token` command-line option.

The skill validates authentication with:

```bash
scripts/check-auth.sh
```

This performs a read-only project request with `--output none`.
It does not print project data, secret metadata, secret values, or the token.

## Example prompts

```text
Use $bitwarden-secrets-manager-cli to install bws if needed and verify authentication without printing vault data.
```

```text
Use $bitwarden-secrets-manager-cli to list the secret IDs and keys available to this machine account without showing values.
```

```text
Use $bitwarden-secrets-manager-cli to run npm start with secrets from project <PROJECT_ID>.
```

```text
Use $bitwarden-secrets-manager-cli to create a secret in project <PROJECT_ID>, keeping the value out of logs and output.
```

Agents can also invoke the skill automatically when a request mentions Bitwarden Secrets Manager, `bws`, `BWS_ACCESS_TOKEN`, machine accounts, or secret injection.

## Safety model

- Keep access tokens and secret values out of prompts, logs, process arguments, and version control.
- Start with read-only discovery before changing remote state.
- Filter `bws secret list` and `bws secret get` output because raw responses include decrypted values.
- Use `--output none` for mutations unless response metadata is required.
- Resolve exact resource IDs before editing or deleting anything.
- Require explicit authorization before deleting projects or secrets.
- Run only trusted commands through `bws run` because the child process receives secret values.
- Treat `--no-inherit-env` as environment cleanup, not as a security sandbox.

## Repository contents

```text
.
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   └── cli-guide.md
└── scripts/
    ├── check-auth.sh
    ├── ensure-bws.sh
    └── list-secret-metadata.sh
```

- [`SKILL.md`](SKILL.md) contains the agent workflow and safety rules.
- [`references/cli-guide.md`](references/cli-guide.md) summarizes installation, authentication, configuration, commands, and troubleshooting.
- [`scripts/ensure-bws.sh`](scripts/ensure-bws.sh) detects or installs the official `bws` CLI on Linux and macOS.
- [`scripts/check-auth.sh`](scripts/check-auth.sh) validates authentication without printing vault data.
- [`scripts/list-secret-metadata.sh`](scripts/list-secret-metadata.sh) strips values and notes from secret-list output.

On native Windows, the skill uses Bitwarden's official PowerShell installer.

## Update or remove

Update the installed skill:

```bash
npx skills update bitwarden-secrets-manager-cli
```

Update a global installation:

```bash
npx skills update bitwarden-secrets-manager-cli --global
```

Remove a project installation:

```bash
npx skills remove bitwarden-secrets-manager-cli
```

Remove a global installation:

```bash
npx skills remove bitwarden-secrets-manager-cli --global
```

## Documentation

- [Bitwarden Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/)
- [Bitwarden access tokens](https://bitwarden.com/help/access-tokens/)
- [Bitwarden Secrets Manager SDK and `bws` releases](https://github.com/bitwarden/sdk-sm)
- [Skills CLI](https://github.com/vercel-labs/skills)
- [Agent Skills specification](https://agentskills.io)

## License

[MIT](LICENSE)
