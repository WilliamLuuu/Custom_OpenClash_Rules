#!/usr/bin/env python3
"""Validate repository-owned custom Clash rules and Subconverter wiring."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from dataclasses import dataclass
from pathlib import Path


CUSTOM_RULE_FILES = (
    "Adobe.list",
    "Betting-Direct.list",
    "Betting-Proxy.list",
    "Crypto.list",
    "Emby-LyreBird.list",
    "PCDN.list",
    "Score-Direct.list",
    "Score-Proxy.list",
    "UK-WiFi-Calling.list",
    "VPN-LyreBird.list",
    "VPN-NiceDuck.list",
    "VPN-PeiQianJiChang.list",
    "VPN-Yuyujc.list",
)
DIRECT_FILES = (
    "Betting-Direct.list",
    "Score-Direct.list",
    "VPN-LyreBird.list",
    "VPN-NiceDuck.list",
    "VPN-PeiQianJiChang.list",
    "VPN-Yuyujc.list",
)
PROXY_FILES = ("Betting-Proxy.list", "Score-Proxy.list")
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX"}
IP_TYPES = {"IP-CIDR", "IP-CIDR6"}
BUILTIN_POLICIES = {"DIRECT", "REJECT"}


@dataclass(frozen=True)
class RuleRecord:
    path: Path
    line_number: int
    rule_type: str
    value: str
    raw: str


def parse_rule_file(path: Path) -> tuple[RuleRecord, ...]:
    records: list[RuleRecord] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        rule = raw_line.strip()
        if not rule or rule.startswith(("#", ";")):
            continue
        parts = [part.strip() for part in rule.split(",")]
        if len(parts) < 2 or not parts[1]:
            raise ValueError(f"{path}:{line_number}: malformed rule: {rule}")
        rule_type, value = parts[0], parts[1]
        if rule_type not in DOMAIN_TYPES | IP_TYPES:
            raise ValueError(f"{path}:{line_number}: unsupported rule type: {rule_type}")
        if rule_type in DOMAIN_TYPES:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                pass
            else:
                raise ValueError(
                    f"{path}:{line_number}: IP address must use IP-CIDR: {value}"
                )
            if rule_type != "DOMAIN-REGEX" and (
                any(character.isspace() for character in value)
                or ":" in value
                or "/" in value
            ):
                raise ValueError(
                    f"{path}:{line_number}: invalid domain payload: {value}"
                )
        else:
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid CIDR: {value}"
                ) from exc
            expected = "IP-CIDR6" if network.version == 6 else "IP-CIDR"
            if rule_type != expected:
                raise ValueError(
                    f"{path}:{line_number}: {value} must use {expected}"
                )
        records.append(RuleRecord(path, line_number, rule_type, value, rule))
    return tuple(records)


def _load_records(root: Path, names: tuple[str, ...], errors: list[str]) -> dict[str, tuple[RuleRecord, ...]]:
    loaded: dict[str, tuple[RuleRecord, ...]] = {}
    for name in names:
        path = root / "rule" / name
        if not path.exists():
            errors.append(f"missing custom rule file: rule/{name}")
            continue
        try:
            records = parse_rule_file(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        seen: set[str] = set()
        for record in records:
            if record.raw in seen:
                errors.append(
                    f"{record.path}:{record.line_number}: duplicate rule: {record.raw}"
                )
            seen.add(record.raw)
        loaded[name] = records
    return loaded


def validate_repository(
    root: Path,
    *,
    custom_rule_files: tuple[str, ...] = CUSTOM_RULE_FILES,
    direct_files: tuple[str, ...] = DIRECT_FILES,
    proxy_files: tuple[str, ...] = PROXY_FILES,
) -> list[str]:
    errors: list[str] = []
    loaded = _load_records(root, custom_rule_files, errors)
    direct = {record.raw for name in direct_files for record in loaded.get(name, ())}
    proxy = {record.raw for name in proxy_files for record in loaded.get(name, ())}
    for conflict in sorted(direct & proxy):
        errors.append(f"DIRECT/PROXY conflict: {conflict}")

    config = root / "cfg" / "Custom_Clash.ini"
    lines = config.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0] != ";Custom_OpenClash_Rules":
        errors.append("cfg/Custom_Clash.ini: invalid first line")

    defined_groups = {
        line.split("`", 1)[0].split("=", 1)[1]
        for line in lines
        if line.startswith("custom_proxy_group=")
    }
    ruleset_groups = {
        line.split("=", 1)[1].split(",", 1)[0]
        for line in lines
        if line.startswith("ruleset=")
    }
    group_references = {
        reference
        for line in lines
        if line.startswith("custom_proxy_group=")
        for reference in re.findall(r"\[\]([^`]+)", line)
    }
    for group in sorted((ruleset_groups | group_references) - defined_groups - BUILTIN_POLICIES):
        errors.append(f"undefined proxy group: {group}")

    referenced_files = {
        match.group(1)
        for line in lines
        for match in [re.search(r"/rule/([^,]+\.list)(?:,|$)", line)]
        if match
    }
    for name in custom_rule_files:
        if name not in referenced_files:
            errors.append(f"unreferenced custom rule file: rule/{name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    errors = validate_repository(args.root.resolve())
    if errors:
        sys.stdout.reconfigure(errors="backslashreplace")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Custom rules and policy-group wiring are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
