"""Run one reviewed Python operation. Credential data stays inside the worker."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import uuid


class ApprovedError(Exception):
    pass


def uuid_text(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ApprovedError()
    return value


def read_private(path, maximum=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > maximum):
            raise ApprovedError()
        return stream.read(maximum + 1)


def load_recipe(home, name):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
        raise ApprovedError()
    config = json.loads(read_private(home / ".config/bws-operations/approved.json"))
    recipe = config[name]
    if set(recipe) != {"script", "sha256", "region", "inputs", "exports"}:
        raise ApprovedError()
    if recipe["region"] not in ("us", "eu") or not Path(recipe["script"]).is_absolute():
        raise ApprovedError()
    if not re.fullmatch(r"[a-f0-9]{64}", recipe["sha256"]):
        raise ApprovedError()
    for mode in ("inputs", "exports"):
        values = recipe[mode]
        if not isinstance(values, dict) or len(values) > 16:
            raise ApprovedError()
        for name, value in values.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise ApprovedError()
            expected = ({"secret_name", "project_id"} if "secret_name" in value else {"secret_id", "project_id"}) if mode == "inputs" else {"project_id", "project_name", "secret_name"}
            if set(value) != expected:
                raise ApprovedError()
            uuid_text(value["project_id"])
            if mode == "inputs":
                if "secret_id" in value:
                    uuid_text(value["secret_id"])
                elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value["secret_name"]):
                    raise ApprovedError()
            else:
                for field in ("project_name", "secret_name"):
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value[field]):
                        raise ApprovedError()
    destinations = [(v["project_id"], v["secret_name"]) for v in recipe["exports"].values()]
    if len(destinations) != len(set(destinations)):
        raise ApprovedError()
    # Execute these exact reviewed bytes, not a path reopened after verification.
    script = read_private(Path(recipe["script"]))
    if hashlib.sha256(script).hexdigest() != recipe["sha256"]:
        raise ApprovedError()
    return recipe, script.decode("utf-8")


def execute_script(script, inputs):
    # Script source is non-secret. It must be self-contained, use fixed
    # destinations/executables, and write only the documented response to stdout.
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", script], env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        # Stay in the worker's process group so its parent can clean up the
        # entire operation even if the worker itself times out.
    )
    try:
        stdout, _ = child.communicate(json.dumps(inputs).encode(), timeout=300)
    except BaseException:
        child.kill()
        child.communicate()
        raise ApprovedError() from None
    if child.returncode != 0 or len(stdout) > 1048576:
        raise ApprovedError()
    response = json.loads(stdout)
    if set(response) != {"exports"} or not isinstance(response["exports"], dict):
        raise ApprovedError()
    return response["exports"]


def perform(client, recipe, script, journal, execute=execute_script, login=None):
    journal.seek(0)
    previous = journal.read()
    if previous:
        if not previous.endswith("\n"):
            raise ApprovedError()
        receipt = json.loads(previous.splitlines()[-1])
        if receipt.get("binding") != recipe or receipt.get("status") != "completed":
            raise ApprovedError()
        return {"status": "recorded", "secret_ids": [uuid_text(v) for v in receipt["secret_ids"]]}

    if login is not None:
        client = login(recipe["region"])
    destinations = {}
    for name, spec in recipe["exports"].items():
        project = client.projects().get(spec["project_id"]).data
        if str(project.id) != spec["project_id"] or project.name != spec["project_name"]:
            raise ApprovedError()
        org = uuid_text(str(project.organization_id))
        if any(item.key == spec["secret_name"] for item in client.secrets().list(org).data.data):
            raise ApprovedError()
        destinations[name] = org

    inputs = {}
    for name, spec in recipe["inputs"].items():
        secret_id = spec.get("secret_id")
        if secret_id is None:
            project = client.projects().get(spec["project_id"]).data
            if str(project.id) != spec["project_id"]:
                raise ApprovedError()
            org = uuid_text(str(project.organization_id))
            matches = [item for item in client.secrets().list(org).data.data if item.key == spec["secret_name"]]
            if len(matches) != 1:
                raise ApprovedError()
            secret_id = uuid_text(str(matches[0].id))
        secret = client.secrets().get(secret_id).data
        if str(secret.id) != secret_id or str(secret.project_id) != spec["project_id"]:
            raise ApprovedError()
        if not isinstance(secret.value, str) or not secret.value or len(secret.value) > 65536:
            raise ApprovedError()
        inputs[name] = secret.value

    def save(status, ids):
        # Append: a crash must never truncate a pending operation back to an
        # apparently unused empty receipt. A partial final line fails closed.
        journal.seek(0, os.SEEK_END)
        journal.write(json.dumps({"binding": recipe, "status": status, "secret_ids": ids}) + "\n")
        journal.flush()
        os.fsync(journal.fileno())

    # Persist uncertainty BEFORE the script can mutate a deployment. A timeout
    # may leave a remote operation running; never automatically repeat it.
    save("pending", [])
    exports = execute(script, inputs)
    if set(exports) != set(destinations):
        raise ApprovedError()
    ids = []
    for name, spec in recipe["exports"].items():
        value = exports[name]
        if not isinstance(value, str) or not value or len(value) > 65536:
            raise ApprovedError()
        result = client.secrets().create(destinations[name], spec["secret_name"], value,
                                         "Imported by approved operation", [spec["project_id"]]).data
        if (str(result.project_id) != spec["project_id"] or str(result.organization_id) != destinations[name]
                or result.key != spec["secret_name"] or result.value != value):
            raise ApprovedError()
        ids.append(uuid_text(str(result.id)))
        save("pending", ids)
    save("completed", ids)
    return {"status": "completed", "secret_ids": ids}


def run(home, name, login):
    recipe, script = load_recipe(home, name)
    state = home / ".local/state/bws-operations"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ApprovedError()
    # Aliases for the same script/destinations share a journal. Changing the
    # script hash does not bypass an uncertain prior execution.
    identity = {key: recipe[key] for key in ("script", "region", "inputs", "exports")}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    fd = os.open(state / ("approved-" + digest + ".json"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as journal:
        info = os.fstat(journal.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 2097152:
            raise ApprovedError()
        fcntl.flock(journal, fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return perform(None, recipe, script, journal, login=login)
