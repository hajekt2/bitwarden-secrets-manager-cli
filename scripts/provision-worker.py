#!/usr/bin/env python3
"""Private worker entrypoint. Parent discards both standard streams."""

import ctypes
import importlib.util
import json
import os
from pathlib import Path
import pwd
import resource
import sys


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # Reduce same-UID /proc and ptrace exposure. This is not a boundary against
    # root or an unrestricted agent capable of replacing this worker.
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        return 1
    if len(sys.argv) != 3 or os.environ.get("BWS_ACCESS_TOKEN"):
        return 1
    result_fd = int(sys.argv[2])
    ops = load_module("operations", "bws-operations.py")
    provisioning = load_module("provisioning", "provision.py")

    def login(region):
        from bitwarden_sdk import BitwardenClient, DeviceType, client_settings_from_dict
        suffix = "com" if region == "us" else "eu"
        client = BitwardenClient(client_settings_from_dict({
            "apiUrl": "https://api.bitwarden." + suffix,
            "identityUrl": "https://identity.bitwarden." + suffix,
            "deviceType": DeviceType.SDK,
            "userAgent": "approved-provisioning",
        }))
        client.auth().login_access_token(ops.keyring_token(ops.command_environment()))
        return client

    result = provisioning.run(Path(pwd.getpwuid(os.getuid()).pw_dir), sys.argv[1], login)
    os.write(result_fd, json.dumps(result).encode("ascii"))
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:
        status = 1
    os._exit(status)
