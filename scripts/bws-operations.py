#!/usr/bin/env python3
"""Fixed operations with selected results. This same-user helper is not a sandbox."""

import ctypes
import json
import os
from pathlib import Path
import pwd
import re
import resource
import signal
import subprocess
import sys
import uuid


KEYRING_EXECUTABLE = Path("/usr/bin/secret-tool")
ENVIRONMENT_TOKEN_SOURCE = "BWS_ACCESS_TOKEN_SOURCE"
ENVIRONMENT_TOKEN_OPT_IN = "environment"
MAXIMUM_TOKEN_BYTES = 8192


class OperationError(Exception):
    pass


class CredentialSourceError(OperationError):
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


def usable_token(value, source):
    if not isinstance(value, str) or not value or "\x00" in value or len(value.encode("utf-8")) > MAXIMUM_TOKEN_BYTES:
        raise CredentialSourceError(f"No usable {source} credential; value suppressed.")
    return value


def token_from_fd():
    descriptor = os.environ.get("BWS_ACCESS_TOKEN_FD")
    if descriptor is None:
        return None
    try:
        fd = int(descriptor)
        if fd < 3:
            raise ValueError
        data = os.read(fd, MAXIMUM_TOKEN_BYTES + 1)
        os.close(fd)
        token = data.decode("utf-8")
    except (OSError, ValueError, UnicodeError):
        raise CredentialSourceError("No usable private-pipe credential; value suppressed.") from None
    return usable_token(token, "private-pipe")


def keyring_token(env):
    piped = token_from_fd()
    if piped is not None:
        return piped
    keyring_env = dict(env)
    for name in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "DISPLAY", "XAUTHORITY"):
        if name in os.environ:
            keyring_env[name] = os.environ[name]
    try:
        data = run_captured(
            [str(KEYRING_EXECUTABLE), "lookup", "service", "bws", "account", "access-token"],
            keyring_env,
        )
    except OperationError:
        raise CredentialSourceError(
            "No credential source is available on this host. Linux keyring lookup failed; child output suppressed."
        ) from None
    try:
        token = data.decode("utf-8").rstrip("\r\n")
    except UnicodeError:
        raise CredentialSourceError("No usable keyring credential; value suppressed.") from None
    return usable_token(token, "keyring")


def keyring_available():
    return KEYRING_EXECUTABLE.is_file() and os.access(KEYRING_EXECUTABLE, os.X_OK)


def credential_token(env):
    inherited = os.environ.get("BWS_ACCESS_TOKEN")
    if not inherited:
        if not keyring_available():
            raise CredentialSourceError(
                "No credential source is available on this host. Linux keyring support is unavailable."
            )
        return keyring_token(env)
    if keyring_available():
        raise CredentialSourceError(
            "Inherited BWS_ACCESS_TOKEN denied. This host has Linux keyring support; use the keyring credential."
        )
    if os.environ.get(ENVIRONMENT_TOKEN_SOURCE) != ENVIRONMENT_TOKEN_OPT_IN:
        raise CredentialSourceError(
            "No credential source is available on this host. Linux keyring support is unavailable and "
            f"{ENVIRONMENT_TOKEN_SOURCE}=environment is not enabled."
        )
    return usable_token(inherited, "environment")


def bws_executable(env):
    # Never resolve a caller-supplied executable or search the agent's PATH.
    for path in (Path(env["HOME"]) / ".local/bin/bws", Path("/usr/local/bin/bws"), Path("/usr/bin/bws")):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise OperationError("bws is not installed at a supported location.")


def selected_projects(output, include_organization=False):
    try:
        projects = json.loads(output)
        if not isinstance(projects, list):
            raise ValueError
        selected = []
        for project in projects:
            name = project["name"]
            if not isinstance(name, str) or len(name) > 256 or "\x00" in name:
                raise ValueError
            item = {"id": str(uuid.UUID(project["id"])), "name": name}
            if include_organization:
                item["organization_id"] = str(uuid.UUID(project["organizationId"]))
            selected.append(item)
        return selected
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise OperationError("Invalid project response; child output suppressed.") from None


def identifier_secret_names(client, projects):
    project_by_id = {project["id"]: project for project in projects}
    duplicate_names = {
        project["name"] for project in projects
        if sum(other["name"] == project["name"] for other in projects) > 1
    }
    selected = []
    organizations = sorted({project["organization_id"] for project in projects})
    for organization_id in organizations:
        identifiers = client.secrets().list(organization_id).data.data
        for identifier in identifiers:
            if not isinstance(identifier.key, str) or len(identifier.key) > 256 or "\x00" in identifier.key:
                raise OperationError("Invalid secret identifier response; child output suppressed.")
            for project_id in sorted({str(value) for value in identifier.project_ids}):
                project = project_by_id.get(project_id)
                if project is None or project["organization_id"] != organization_id:
                    continue
                item = {"project": project["name"], "key": identifier.key}
                if project["name"] in duplicate_names:
                    item["project_id"] = project_id
                selected.append(item)
    return sorted(selected, key=lambda item: (item["project"], item.get("project_id", ""), item["key"]))


def secret_names_worker(region):
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            return 1
        payload = json.loads(sys.stdin.buffer.read(1048577))
        if set(payload) != {"token", "projects"} or len(json.dumps(payload).encode()) > 1048576:
            raise ValueError
        token = usable_token(payload["token"], "environment")
        projects = payload["projects"]
        if not isinstance(projects, list) or len(projects) > 10000:
            raise ValueError
        for project in projects:
            if set(project) != {"id", "name", "organization_id"}:
                raise ValueError
            project["id"] = str(uuid.UUID(project["id"]))
            project["organization_id"] = str(uuid.UUID(project["organization_id"]))
            if not isinstance(project["name"], str) or len(project["name"]) > 256 or "\x00" in project["name"]:
                raise ValueError
        from bitwarden_sdk import BitwardenClient, DeviceType, client_settings_from_dict
        suffix = "com" if region == "us" else "eu"
        client = BitwardenClient(client_settings_from_dict({
            "apiUrl": "https://api.bitwarden." + suffix,
            "identityUrl": "https://identity.bitwarden." + suffix,
            "deviceType": DeviceType.SDK,
            "userAgent": "secret-name-enumeration",
        }))
        client.auth().login_access_token(token)
        print(json.dumps(identifier_secret_names(client, projects), ensure_ascii=True))
        return 0
    except BaseException:
        return 1


def sdk_secret_names(region, token, projects, env):
    executable = Path(env["HOME"]) / ".local/share/bws-operations/venv/bin/python"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise OperationError("Bitwarden SDK worker is not installed at the supported location.")
    payload = json.dumps({"token": token, "projects": projects}).encode()
    try:
        result = subprocess.run(
            [str(executable), "-I", str(Path(__file__)), "--secret-names-worker", region],
            env=env, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise OperationError(
            "Credential was found, but the vault request failed or rejected it; child output suppressed."
        ) from None
    if result.returncode != 0:
        raise OperationError(
            "Credential was found, but the vault request failed or rejected it; child output suppressed."
        )
    try:
        selected = json.loads(result.stdout)
        if not isinstance(selected, list) or len(selected) > 100000:
            raise ValueError
        project_ids_by_name = {}
        for project in projects:
            project_ids_by_name.setdefault(project["name"], set()).add(project["id"])
        for item in selected:
            project_ids = project_ids_by_name.get(item.get("project"))
            if not project_ids:
                raise ValueError
            expected = {"project", "key", "project_id"} if len(project_ids) > 1 else {"project", "key"}
            if set(item) != expected:
                raise ValueError
            if not all(isinstance(item[name], str) and len(item[name]) <= 256 and "\x00" not in item[name]
                       for name in ("project", "key")):
                raise ValueError
            if "project_id" in item:
                item["project_id"] = str(uuid.UUID(item["project_id"]))
                if item["project_id"] not in project_ids:
                    raise ValueError
        rendered = json.dumps(selected, ensure_ascii=True, indent=2)
        if token in rendered:
            raise ValueError
        return rendered
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise OperationError("Invalid secret identifier response; child output suppressed.") from None


def execute(operation, region=None):
    if operation not in {"check-auth", "projects", "secret-names"}:
        raise OperationError("Operation denied. Allowed operations: check-auth, projects, secret-names.")

    env = command_environment()
    executable = bws_executable(env)
    token = credential_token(env)
    # Only the bws child receives the token; never put it in os.environ.
    try:
        output = run_captured(
            [executable, "project", "list", "--output", "none" if operation == "check-auth" else "json"],
            {**env, "BWS_ACCESS_TOKEN": token},
        )
    except OperationError:
        raise OperationError(
            "Credential was found, but the vault request failed or rejected it; child output suppressed."
        ) from None
    if operation == "check-auth":
        return "bws authentication succeeded with a read-only project check."
    projects = selected_projects(output, include_organization=operation == "secret-names")
    if operation == "secret-names":
        return sdk_secret_names(region, token, projects, env)
    rendered = json.dumps(projects, ensure_ascii=True, indent=2)
    if token in rendered:
        raise OperationError("Invalid project response; child output suppressed.")
    return rendered


def main(args):
    if len(args) == 2 and args[0] == "secret-names" and args[1] in ("us", "eu"):
        operation, region = "secret-names", args[1]
    else:
        operation, region = None, None
    if len(args) == 2 and args[0] == "inspect-approved" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1], approved=True, inspect=True))
            return 0
        except CredentialSourceError as error:
            print(str(error), file=sys.stderr)
            return 1
        except Exception:
            print("Binding inspection failed; output suppressed.", file=sys.stderr)
            return 1
    if len(args) == 2 and args[0] == "run-approved" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1], approved=True))
            return 0
        except CredentialSourceError as error:
            print(str(error), file=sys.stderr)
            return 1
        except Exception:
            print("Approved operation failed; output suppressed. Reconcile pending operations before retrying.", file=sys.stderr)
            return 1
    if len(args) == 2 and args[0] == "provision-generated" and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args[1]):
        try:
            print(provision_generated(args[1]))
            return 0
        except CredentialSourceError as error:
            print(str(error), file=sys.stderr)
            return 1
        except Exception:
            print("Provisioning failed; output suppressed. Do not delete receipts or retry uncertain writes.", file=sys.stderr)
            return 1
    # Exact compatibility forms only. No generic command forwarding.
    legacy = {
        ("bws", "project", "list", "--output", "none"): "check-auth",
        ("bws", "project", "list", "--output", "table"): "projects",
    }
    operation = operation or (args[0] if len(args) == 1 else legacy.get(tuple(args)))
    if operation == "secret-names" and region is None:
        operation = None
    if operation not in {"check-auth", "projects", "secret-names"}:
        print("Operation denied. Use check-auth, projects, secret-names REGION, provision-generated RECIPE, or run-approved RECIPE.", file=sys.stderr)
        return 2
    try:
        print(execute(operation, region))
        return 0
    except OperationError as error:
        print(str(error), file=sys.stderr)
        return 1


def provision_generated(name, approved=False, inspect=False):
    env = command_environment()
    inherited_token = os.environ.get("BWS_ACCESS_TOKEN")
    token = credential_token(env) if inherited_token or os.environ.get(ENVIRONMENT_TOKEN_SOURCE) == ENVIRONMENT_TOKEN_OPT_IN else None
    for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "DISPLAY", "XAUTHORITY"):
        if key in os.environ:
            env[key] = os.environ[key]
    executable = Path(env["HOME"]) / ".local/share/bws-operations/venv/bin/python"
    read_fd, write_fd = os.pipe()
    token_read_fd = token_write_fd = -1
    try:
        pass_fds = [write_fd]
        if token is not None:
            token_read_fd, token_write_fd = os.pipe()
            env["BWS_ACCESS_TOKEN_FD"] = str(token_read_fd)
            pass_fds.append(token_read_fd)
        # No secret enters argv or the child environment.
        child = subprocess.Popen(
            [str(executable), "-I", str(Path(__file__).with_name("provision-worker.py")), name, str(write_fd)] + (["inspect-approved" if inspect else "run-approved"] if approved else []),
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=tuple(pass_fds), start_new_session=True,
        )
        if token_read_fd >= 0:
            os.close(token_read_fd)
            token_read_fd = -1
            os.write(token_write_fd, token.encode("utf-8"))
            os.close(token_write_fd)
            token_write_fd = -1
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
        if token_read_fd >= 0:
            os.close(token_read_fd)
        if token_write_fd >= 0:
            os.close(token_write_fd)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--secret-names-worker" and sys.argv[2] in ("us", "eu"):
        raise SystemExit(secret_names_worker(sys.argv[2]))
    raise SystemExit(main(sys.argv[1:]))
