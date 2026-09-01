from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Mapping


ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLAIN_VALUE = re.compile(r"^[A-Za-z0-9_./:@%+,-]*$")


def decode_env_value(raw: str) -> str:
    value = raw.strip()
    if not value or value[0] not in {'"', "'"}:
        return value
    try:
        parts = shlex.split(value, posix=True)
    except ValueError as exc:
        raise ValueError("invalid quoted environment value") from exc
    if len(parts) != 1:
        raise ValueError("quoted environment value must decode to one value")
    return parts[0]


def encode_env_value(value: object) -> str:
    text = str(value)
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError("environment values cannot contain line breaks or NUL bytes")
    if PLAIN_VALUE.fullmatch(text):
        return text
    if "'" not in text:
        return f"'{text}'"
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not ENV_KEY.fullmatch(key):
            raise ValueError(f"invalid environment entry on line {number}")
        values[key] = decode_env_value(raw_value)
    return values


def load_env_file(path: str | Path, *, overwrite: bool = False) -> None:
    for key, value in parse_env_file(path).items():
        if overwrite or key not in os.environ:
            os.environ[key] = value


def update_env_file(path: str | Path, updates: Mapping[str, object], *, mode: int = 0o640) -> None:
    env_path = Path(path)
    invalid = [key for key in updates if not ENV_KEY.fullmatch(key)]
    if invalid:
        raise ValueError(f"invalid environment key: {invalid[0]}")
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    encoded = {key: encode_env_value(value) for key, value in updates.items()}
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key, separator, _ = line.partition("=")
        if separator and key in encoded:
            output.append(f"{key}={encoded[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in encoded.items():
        if key not in seen:
            output.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{env_path.name}-", dir=env_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, env_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
