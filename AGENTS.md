# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Read `references/approved-operations.md` before changing `run-approved`.
  Reviewed operation scripts live in the repository that owns the work. This
  repository owns the credential wrapper and its public result validation.
- Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` and
  the shell syntax command in `README.md` after wrapper changes.
- The SDK virtual environment at `~/.local/share/bws-operations/venv` must be
  built with `--copies`: a symlinked interpreter stops matching its own
  `site-packages` when the operating system moves `python3` to a newer series.
  Setup and repair steps live in `references/provisioning.md`; `sdk_worker`
  probes the SDK import before any credential reaches the interpreter.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
