#!/usr/bin/env python3
"""Fixed operations with selected results. This same-user helper is not a sandbox."""

import json
import os
from pathlib import Path
import pwd
import re
import signal
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
    if len(args) == 2 and args[0] == "inspect-approved" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1], approved=True, inspect=True))
            return 0
        except Exception:
            print("Binding inspection failed; output suppressed.", file=sys.stderr)
            return 1
    if len(args) == 2 and args[0] == "run-approved" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1], approved=True))
            return 0
        except Exception:
            print("Approved operation failed; output suppressed. Reconcile pending operations before retrying.", file=sys.stderr)
            return 1
    if len(args) == 2 and args[0] == "provision-generated" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1]))
            return 0
        except Exception:
            print("Provisioning failed; output suppressed. Do not delete receipts or retry uncertain writes.", file=sys.stderr)
            return 1
    # Exact compatibility forms only. No generic command forwarding.
    legacy = {
        ("bws", "project", "list", "--output", "none"): "check-auth",
        ("bws", "project", "list", "--output", "table"): "projects",
    }
    operation = args[0] if len(args) == 1 else legacy.get(tuple(args))
    if operation not in {"check-auth", "projects"}:
        print("Operation denied. Use check-auth, projects, provision-generated RECIPE, or run-approved RECIPE.", file=sys.stderr)
        return 2
    try:
        print(execute(operation))
        return 0
    except OperationError as error:
        print(str(error), file=sys.stderr)
        return 1


def provision_generated(name, approved=False, inspect=False):
    if os.environ.get("BWS_ACCESS_TOKEN"):
        raise OperationError()
    env = command_environment()
    for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "DISPLAY", "XAUTHORITY"):
        if key in os.environ:
            env[key] = os.environ[key]
    executable = Path(env["HOME"]) / ".local/share/bws-operations/venv/bin/python"
    read_fd, write_fd = os.pipe()
    try:
        # No secret enters argv, parent environment, or parent Python memory.
        child = subprocess.Popen(
            [str(executable), "-I", str(Path(__file__).with_name("provision-worker.py")), name, str(write_fd)] + (["inspect-approved" if inspect else "run-approved"] if approved else []),
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(write_fd,), start_new_session=True,
        )
        try:
            child.wait(timeout=360 if approved else 90)
        finally:
            # Also reap descendants after a successful worker exit. Reviewed
            # operations must not detach or leave background credential users.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        if child.returncode != 0:
            raise OperationError()
        os.close(write_fd)
        write_fd = -1
        result = json.loads(os.read(read_fd, 4096))
        if inspect:
            if set(result) != {'status','bindings'} or result['status'] != 'bindings' or not isinstance(result['bindings'],list) or len(result['bindings']) > 16:
                raise OperationError()
            for item in result['bindings']:
                if set(item) != {'alias','secret_ids'} or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',item['alias']) or not isinstance(item['secret_ids'],list) or len(item['secret_ids']) > 16:
                    raise OperationError()
                item['secret_ids'] = [str(uuid.UUID(v)) for v in item['secret_ids']]
            return json.dumps(result)
        if approved:
            if (set(result) != {"status", "secret_ids"} or result["status"] not in ("completed", "recorded")
                    or not isinstance(result["secret_ids"], list) or len(result["secret_ids"]) > 16):
                raise OperationError()
            return json.dumps({"status": result["status"], "secret_ids": [str(uuid.UUID(v)) for v in result["secret_ids"]]})
        if set(result) != {"status", "secret_id"} or result["status"] not in ("created", "recorded"):
            raise OperationError()
        return json.dumps({"status": result["status"], "secret_id": str(uuid.UUID(result["secret_id"]))})
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
