from __future__ import annotations

from pathlib import Path


def load_config(path: Path | str) -> dict:
    config_path = Path(path)
    try:
        import yaml  # type: ignore

        with config_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except ModuleNotFoundError:
        return _load_simple_yaml(config_path)


def _load_simple_yaml(path: Path) -> dict:
    lines = [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    root: dict = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(" "):
            index += 1
            continue
        key, raw = _split_key_value(line)
        if raw:
            root[key] = _parse_scalar(raw)
            index += 1
            continue
        block, index = _parse_block(lines, index + 1, 2)
        root[key] = block
    return root


def _parse_block(lines: list[str], index: int, indent: int):
    items_at_level = [line for line in lines[index:] if _indent(line) == indent]
    if items_at_level and items_at_level[0].lstrip().startswith("- "):
        result = []
        while index < len(lines) and _indent(lines[index]) >= indent:
            line = lines[index]
            if _indent(line) == indent and line.lstrip().startswith("- "):
                result.append(_parse_scalar(line.strip()[2:]))
            index += 1
        return result, index

    result: dict = {}
    while index < len(lines):
        line = lines[index]
        current_indent = _indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            index += 1
            continue
        key, raw = _split_key_value(line.strip())
        if raw:
            result[key] = _parse_scalar(raw)
            index += 1
        else:
            child, index = _parse_block(lines, index + 1, indent + 2)
            result[key] = child
    return result, index


def _split_key_value(line: str) -> tuple[str, str]:
    key, _, raw = line.partition(":")
    return key.strip(), raw.strip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_scalar(value: str):
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value
