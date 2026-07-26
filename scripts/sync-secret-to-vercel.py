#!/usr/bin/env python3

"""Copy one Bitwarden secret to Vercel without exposing its value."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VERCEL_ENVIRONMENT_KEYS = {
    "CI",
    "HOME",
    "LANG",
    "LC_ALL",
    "NO_COLOR",
    "PATH",
    "TMPDIR",
    "VERCEL_ORG_ID",
    "VERCEL_PROJECT_ID",
    "VERCEL_TOKEN",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy one Bitwarden secret to a Vercel environment variable."
    )
    parser.add_argument("secret_id", help="Bitwarden secret UUID")
    parser.add_argument("variable_name", help="Vercel environment variable name")
    parser.add_argument(
        "environment",
        choices=("production", "preview", "development"),
        help="Vercel environment target",
    )
    parser.add_argument(
        "--git-branch",
        help="Optional Git branch for a Preview environment variable",
    )
    return parser.parse_args()


def validate_arguments(arguments: argparse.Namespace) -> None:
    try:
        parsed_secret_id = uuid.UUID(arguments.secret_id)
    except ValueError as error:
        raise ValueError("SECRET_ID must be a UUID.") from error

    if str(parsed_secret_id) != arguments.secret_id.lower():
        raise ValueError("SECRET_ID must use the canonical UUID form.")

    if not ENVIRONMENT_VARIABLE_PATTERN.fullmatch(arguments.variable_name):
        raise ValueError(
            "VARIABLE_NAME must be a valid environment variable identifier."
        )

    if arguments.git_branch and arguments.environment != "preview":
        raise ValueError("--git-branch is supported only for the preview target.")

    if arguments.git_branch and any(
        character.isspace() or ord(character) < 32
        for character in arguments.git_branch
    ):
        raise ValueError("Git branch must not contain whitespace or control characters.")


def retrieve_secret(script_dir: Path, secret_id: str) -> bytes:
    result = subprocess.run(
        [
            str(script_dir / "with-bws-token.sh"),
            "bws",
            "secret",
            "get",
            secret_id,
            "--output",
            "json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Bitwarden secret retrieval failed. No command output was displayed."
        )

    try:
        payload = json.loads(result.stdout)
        secret_value = payload["value"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(
            "Bitwarden returned an invalid secret response. No response was displayed."
        ) from error

    if not isinstance(secret_value, str) or not secret_value:
        raise RuntimeError("Bitwarden returned an empty or non-string secret value.")

    return secret_value.encode()


def vercel_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key in VERCEL_ENVIRONMENT_KEYS
    }


def sync_to_vercel(
    vercel_command: str,
    variable_name: str,
    environment: str,
    git_branch: str | None,
    secret_value: bytes,
) -> None:
    command = [
        vercel_command,
        "env",
        "add",
        variable_name,
        environment,
    ]

    if git_branch:
        command.append(git_branch)

    command.extend(("--force", "--yes", "--no-color"))

    result = subprocess.run(
        command,
        input=secret_value,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=vercel_environment(),
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Vercel environment update failed. No command output was displayed."
        )


def main() -> int:
    arguments = parse_arguments()

    try:
        validate_arguments(arguments)
        vercel_command = shutil.which("vercel")
        if not vercel_command:
            raise RuntimeError("The Vercel CLI is not installed or not on PATH.")

        script_dir = Path(__file__).resolve().parent
        secret_value = retrieve_secret(script_dir, arguments.secret_id)
        sync_to_vercel(
            vercel_command,
            arguments.variable_name,
            arguments.environment,
            arguments.git_branch,
            secret_value,
        )
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    target = arguments.environment
    if arguments.git_branch:
        target = f"{target}:{arguments.git_branch}"

    print(f"Updated Vercel variable {arguments.variable_name} for {target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
