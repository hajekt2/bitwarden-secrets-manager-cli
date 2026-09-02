#!/usr/bin/env python3
"""Fixed, read-only operations. This same-user helper is not a sandbox."""

import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import uuid


class OperationError(Exception):
    pass


def command_environment():
    # Do not propagate agent tokens, debug hooks, config overrides, or PATH.
    home = pwd.getpwuid(os.getuid()).pw_dir
    return {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def run_captured(argv, env):
    try:
        result = subprocess.run(
            argv, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise OperationError("Credential operation failed; child output suppressed.") from None
    if result.returncode != 0:
        raise OperationError("Credential operation failed; child output suppressed.")
    return result.stdout


def keyring_token(env):
    keyring_env = dict(env)
    for name in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "DISPLAY", "XAUTHORITY"):
        if name in os.environ:
            keyring_env[name] = os.environ[name]
    data = run_captured(
        ["/usr/bin/secret-tool", "lookup", "service", "bws", "account", "access-token"],
        keyring_env,
    )
    try:
        token = data.decode("utf-8").rstrip("\r\n")
    except UnicodeError:
        raise OperationError("Invalid keyring credential; value suppressed.") from None
    if not token or "\x00" in token:
        raise OperationError("No usable keyring credential. Unlock the user keyring.")
    return token


def bws_executable(env):
    # Never resolve a caller-supplied executable or search the agent's PATH.
    for path in (Path(env["HOME"]) / ".local/bin/bws", Path("/usr/local/bin/bws"), Path("/usr/bin/bws")):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise OperationError("bws is not installed at a supported location.")


def execute(operation):
    if operation not in {"check-auth", "projects"}:
        raise OperationError("Operation denied. Allowed operations: check-auth, projects.")
    if os.environ.get("BWS_ACCESS_TOKEN"):
        raise OperationError("Inherited BWS_ACCESS_TOKEN denied. Keep the token in the keyring.")

    env = command_environment()
    executable = bws_executable(env)
    token = keyring_token(env)
    # Only the bws child receives the token; never put it in os.environ.
    output = run_captured(
        [executable, "project", "list", "--output", "none" if operation == "check-auth" else "json"],
        {**env, "BWS_ACCESS_TOKEN": token},
    )
    if operation == "check-auth":
        return "bws authentication succeeded with a read-only project check."
    try:
        projects = json.loads(output)
        if not isinstance(projects, list):
            raise ValueError
        selected = []
        for project in projects:
            name = project["name"]
            if not isinstance(name, str) or len(name) > 256:
                raise ValueError
            selected.append({"id": str(uuid.UUID(project["id"])), "name": name})
        rendered = json.dumps(selected, ensure_ascii=True, indent=2)
        if token in rendered:
            raise ValueError
        return rendered
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise OperationError("Invalid project response; child output suppressed.") from None


def main(args):
    # Exact compatibility forms only. No generic command forwarding.
    legacy = {
        ("bws", "project", "list", "--output", "none"): "check-auth",
        ("bws", "project", "list", "--output", "table"): "projects",
    }
    operation = args[0] if len(args) == 1 else legacy.get(tuple(args))
    if operation not in {"check-auth", "projects"}:
        print("Operation denied. Allowed operations: check-auth, projects.", file=sys.stderr)
        return 2
    try:
        print(execute(operation))
        return 0
    except OperationError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
