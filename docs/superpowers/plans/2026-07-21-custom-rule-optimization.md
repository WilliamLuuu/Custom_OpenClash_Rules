# Custom OpenClash Rule Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair invalid custom rules, preserve external UK/PCDN updates, remove proven routing conflicts and false positives, and make future regressions fail automated validation.

**Architecture:** Add one focused offline validator for repository-owned custom rules and `Custom_Clash.ini`, then use that validator to drive the configuration and rule cleanup. Keep third-party UK/PCDN feeds as external layers while treating local lists as curated supplements; external reachability remains a separate network check.

**Tech Stack:** Python 3.13 standard library, `unittest`, Subconverter INI rules, Clash/Mihomo classical rules, Git submodules, GitHub Actions.

## Global Constraints

- Keep both external and local UK Wi-Fi Calling rule references.
- Replace the dead PCDN URL with `https://raw.githubusercontent.com/uselibrary/PCDN/main/pcdn.list` and keep the local PCDN reference.
- Preserve `DOMAIN-KEYWORD` as a supported and intentionally used rule type.
- Keep `betboom` only in `rule/Betting-Proxy.list`.
- Keep nonstandard-port routing disabled.
- Keep `google-cn` routed through `🇬 谷歌服务`; update only its stale comment.
- Do not edit unrelated upstream files or regenerate unrelated rule providers.

---

## File Map

- Create `py/validate_custom_rules.py`: offline parser and repository consistency validator.
- Create `py/test_validate_custom_rules.py`: unit and repository-level regression tests.
- Modify `.github/workflows/validate.yml`: run the new offline validator in CI.
- Modify `cfg/Custom_Clash.ini`: repair header, external sources, comments, and UK group wiring.
- Modify `rule/Adobe.list`: remove overbroad Adobe matches and repair malformed hosts.
- Modify `rule/Betting-Direct.list`: remove one duplicate and two proven wrong DIRECT matches.
- Modify `rule/PCDN.list`: remove the unrelated Unlayer CDN match.
- Modify `rule/VPN-LyreBird.list`: represent the server IP as CIDR.
- Delete `rule/VPN-Yujc.list`: remove the unreferenced duplicate.
- Modify `rule/README.md`: document every custom ruleset and its policy/source model.
- Modify `overwrite/OpenClash_Overwrite`: restore the submodule gitlink recorded by `upstream/main`.

---

### Task 1: Add offline custom-rule validation

**Files:**
- Create: `py/validate_custom_rules.py`
- Create: `py/test_validate_custom_rules.py`
- Modify: `.github/workflows/validate.yml:70-81`

**Interfaces:**
- Produces: `parse_rule_file(path: Path) -> tuple[RuleRecord, ...]`
- Produces: `validate_repository(root: Path) -> list[str]`
- Produces: CLI `python py/validate_custom_rules.py` returning 0 on success and 1 with one `ERROR:` line per failure.

- [ ] **Step 1: Write focused failing unit tests**

Create `py/test_validate_custom_rules.py` with fixture-based tests that define the required validator behavior:

```python
import tempfile
import unittest
from pathlib import Path

import validate_custom_rules


class RuleParsingTests(unittest.TestCase):
    def test_rejects_ip_encoded_as_domain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.list"
            source.write_text("DOMAIN,38.59.246.49\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "IP address must use IP-CIDR"):
                validate_custom_rules.parse_rule_file(source)

    def test_rejects_compound_domain_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.list"
            source.write_text("DOMAIN,stats.adobe.com:1 udps.adobe.com\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid domain payload"):
                validate_custom_rules.parse_rule_file(source)

    def test_preserves_domain_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "ok.list"
            source.write_text("DOMAIN-KEYWORD,imdj\n", encoding="utf-8")
            records = validate_custom_rules.parse_rule_file(source)
        self.assertEqual(records[0].rule_type, "DOMAIN-KEYWORD")
        self.assertEqual(records[0].value, "imdj")


class RepositoryValidationTests(unittest.TestCase):
    def test_reports_duplicates_policy_conflicts_and_missing_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rule").mkdir()
            (root / "cfg").mkdir()
            (root / "rule" / "Direct.list").write_text(
                "DOMAIN-KEYWORD,duplicate\nDOMAIN-KEYWORD,duplicate\n",
                encoding="utf-8",
            )
            (root / "rule" / "Proxy.list").write_text(
                "DOMAIN-KEYWORD,duplicate\n",
                encoding="utf-8",
            )
            (root / "cfg" / "Custom_Clash.ini").write_text(
                ";Custom_OpenClash_Rules\n[custom]\n"
                "ruleset=Proxy,https://example.test/rule/Proxy.list,28800\n"
                "custom_proxy_group=Proxy`select`[]Missing Group\n",
                encoding="utf-8",
            )
            errors = validate_custom_rules.validate_repository(
                root,
                custom_rule_files=("Direct.list", "Proxy.list"),
                direct_files=("Direct.list",),
                proxy_files=("Proxy.list",),
            )
        self.assertTrue(any("duplicate rule" in error for error in errors))
        self.assertTrue(any("DIRECT/PROXY conflict" in error for error in errors))
        self.assertTrue(any("undefined proxy group: Missing Group" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify it fails for the missing module**

Run:

```powershell
Push-Location py
python -B -m unittest -v test_validate_custom_rules.py
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'validate_custom_rules'`.

- [ ] **Step 3: Implement the validator**

Create `py/validate_custom_rules.py` with these exact public types and checks:

```python
#!/usr/bin/env python3
"""Validate repository-owned custom Clash rules and Subconverter wiring."""

from __future__ import annotations

import argparse
import ipaddress
import re
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
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Custom rules and policy-group wiring are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run validator unit tests and verify they pass**

Run the Step 2 command again.

Expected: 3 tests pass and exit code 0.

- [ ] **Step 5: Wire the validator into CI**

In `.github/workflows/validate.yml`, add the following immediately after the `python -m unittest discover` line:

```yaml
          python py/validate_custom_rules.py
```

- [ ] **Step 6: Run the current repository validation and record the expected red state**

Run:

```powershell
python -B py/validate_custom_rules.py
```

Expected: exit code 1 with errors covering the invalid INI first line, malformed Adobe rule, IP-as-domain rule, duplicate `csapi`, DIRECT/PROXY `betboom`, missing `🇬🇧 英国节点`, and unreferenced `VPN-Yujc.list` or `PCDN.list`.

- [ ] **Step 7: Commit the validation harness**

```powershell
git add -- py/validate_custom_rules.py py/test_validate_custom_rules.py .github/workflows/validate.yml
git commit --no-gpg-sign -m "test: validate custom Clash rules"
```

---

### Task 2: Repair custom rules and policy-group wiring

**Files:**
- Modify: `cfg/Custom_Clash.ini:1,14-29,40-41,96-137`
- Modify: `rule/Adobe.list:8,26,29`
- Modify: `rule/Betting-Direct.list:33,67,90`
- Modify: `rule/PCDN.list:174`
- Modify: `rule/VPN-LyreBird.list:9`
- Delete: `rule/VPN-Yujc.list`
- Test: `py/test_validate_custom_rules.py`

**Interfaces:**
- Consumes: `validate_repository(root: Path) -> list[str]` from Task 1.
- Produces: a clean repository-owned rule set and complete `Custom_Clash.ini` group graph.

- [ ] **Step 1: Add the repository-level failing regression test**

Append this test class to `py/test_validate_custom_rules.py`:

```python
class LiveRepositoryValidationTests(unittest.TestCase):
    def test_repository_custom_rules_are_valid(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(validate_custom_rules.validate_repository(root), [])
```

- [ ] **Step 2: Run the repository test and verify it fails on current defects**

Run:

```powershell
Push-Location py
python -B -m unittest -v test_validate_custom_rules.LiveRepositoryValidationTests
Pop-Location
```

Expected: FAIL showing the current validator error list.

- [ ] **Step 3: Repair and reorganize `Custom_Clash.ini`**

Apply these exact semantic changes:

```diff
-u;Custom_OpenClash_Rules
+;Custom_OpenClash_Rules
 ruleset=🌎 UK-WiFi-Calling,https://raw.githubusercontent.com/iniwex5/tools/refs/heads/main/rules/UK-wifi-call.list,28800
 ruleset=🌎 UK-WiFi-Calling,https://raw.githubusercontent.com/WilliamLuuu/Custom_OpenClash_Rules/refs/heads/main/rule/UK-WiFi-Calling.list,28800
-ruleset=🌐 PCDN,https://raw.githubusercontent.com/iniwex5/tools/refs/heads/main/rules/PCDN.list,28800
+ruleset=🌐 PCDN,https://raw.githubusercontent.com/uselibrary/PCDN/main/pcdn.list,28800
+ruleset=🌐 PCDN,https://raw.githubusercontent.com/WilliamLuuu/Custom_OpenClash_Rules/refs/heads/main/rule/PCDN.list,28800
-;谷歌在国内可用的域名直连
+;谷歌在国内可用的域名使用谷歌服务策略
```

Update the manual group to include `[]🇬🇧 英国节点` before the final node regex. Keep the existing UK Wi-Fi Calling group, and add this regional group immediately after the Korean group:

```ini
custom_proxy_group=🇬🇧 英国节点`url-test`(🇬🇧|英国|伦敦|曼彻斯特|\bUK(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|\bGB(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|United Kingdom|UNITED KINGDOM|Britain|England|London|Manchester|LHR|MAN)`https://cp.cloudflare.com/generate_204`300,,50
```

Do not uncomment either nonstandard-port line.

- [ ] **Step 4: Repair the repository-owned rule files**

Make only these content edits:

```diff
# rule/Adobe.list
-DOMAIN-SUFFIX,adobe.io
-DOMAIN,stats.adobe.com:1 udps.adobe.com
+DOMAIN,stats.adobe.com
+DOMAIN,udps.adobe.com
-DOMAIN,www.adobe.com

# rule/Betting-Direct.list
-DOMAIN-KEYWORD,csapi  # remove the second occurrence only
-DOMAIN-KEYWORD,cloudfront
-DOMAIN-KEYWORD,betboom

# rule/PCDN.list
-DOMAIN-SUFFIX,cdn.tools.unlayer.com

# rule/VPN-LyreBird.list
-DOMAIN,38.59.246.49
+IP-CIDR,38.59.246.49/32,no-resolve
```

Delete `rule/VPN-Yujc.list`; retain `rule/VPN-Yuyujc.list` unchanged.

- [ ] **Step 5: Run the repository validator and unit tests**

Run:

```powershell
python -B py/validate_custom_rules.py
Push-Location py
python -B -m unittest -v test_validate_custom_rules.py
Pop-Location
```

Expected: validator exit code 0 and all custom validator tests pass.

- [ ] **Step 6: Verify both external update sources are live and text-compatible**

Run:

```powershell
$urls = @(
  'https://raw.githubusercontent.com/iniwex5/tools/refs/heads/main/rules/UK-wifi-call.list',
  'https://raw.githubusercontent.com/uselibrary/PCDN/main/pcdn.list'
)
foreach ($url in $urls) {
  $response = Invoke-WebRequest -Uri $url -UseBasicParsing
  if ($response.StatusCode -ne 200 -or $response.Content -notmatch 'DOMAIN|IP-CIDR') {
    throw "Invalid external ruleset: $url"
  }
}
```

Expected: both URLs return HTTP 200 and contain Clash rule tokens.

- [ ] **Step 7: Commit the rule and configuration repair**

```powershell
git add -- cfg/Custom_Clash.ini rule/Adobe.list rule/Betting-Direct.list rule/PCDN.list rule/VPN-LyreBird.list rule/VPN-Yujc.list py/test_validate_custom_rules.py
git commit --no-gpg-sign -m "fix: tighten custom routing rules"
```

---

### Task 3: Restore the submodule, document ownership, and verify everything

**Files:**
- Modify: `overwrite/OpenClash_Overwrite`
- Modify: `rule/README.md:9-22`

**Interfaces:**
- Consumes: clean validator and rule graph from Tasks 1-2.
- Produces: documented rule ownership and the upstream-recorded overwrite submodule revision.

- [ ] **Step 1: Restore the submodule revision recorded by upstream**

Run:

```powershell
git submodule update --init overwrite/OpenClash_Overwrite
git -C overwrite/OpenClash_Overwrite fetch origin
git -C overwrite/OpenClash_Overwrite checkout 44dd04a8d5660f86da94b101daf323f4af70e5e0
git add -- overwrite/OpenClash_Overwrite
```

Expected: `git diff --submodule=short upstream/main...HEAD -- overwrite/OpenClash_Overwrite` no longer shows the local rollback after the eventual commit.

- [ ] **Step 2: Expand the custom rule inventory in `rule/README.md`**

Add a `## 🧭 本仓库自定义分流规则` section after the existing four-row rule table with this ownership table:

```markdown
| 规则文件 | 策略 | 维护方式 |
| :--- | :---: | :--- |
| `Adobe.list` | REJECT | 本地精确规则 |
| `Betting-Direct.list` | DIRECT | 本地维护，允许 `DOMAIN-KEYWORD` |
| `Betting-Proxy.list` | Betting | 本地维护，优先级不得与 DIRECT 重叠 |
| `Score-Direct.list` | DIRECT | 本地精确规则 |
| `Score-Proxy.list` | Betting | 本地精确规则 |
| `Crypto.list` | Crypto | 本地维护 |
| `Emby-LyreBird.list` | LyreBirdEmby | 本地维护 |
| `PCDN.list` | REJECT | 外部源更新加本地补充 |
| `UK-WiFi-Calling.list` | UK-WiFi-Calling | 外部源更新加本地补充 |
| `VPN-LyreBird.list` | DIRECT | 本地维护 |
| `VPN-NiceDuck.list` | DIRECT | 本地维护 |
| `VPN-PeiQianJiChang.list` | DIRECT | 本地维护 |
| `VPN-Yuyujc.list` | DIRECT | 本地维护 |
```

State immediately below the table that these custom `.list` files are consumed directly by Subconverter and are not inputs to `py/generate_rules.py`.

- [ ] **Step 3: Run the complete local verification suite**

Run:

```powershell
python -B -m unittest discover -s py -p 'test_*.py' -v
python -B py/validate_custom_rules.py
python -B py/generate_rules.py --check
python -B py/generate_game_cdn.py --check
python -B py/update_encrypted_dns.py --check
git diff --check HEAD -- . ':(exclude)rule/Betting-Direct.list' ':(exclude)rule/VPN-LyreBird.list'
git status --short --branch
```

Expected: all tests and rule checks exit 0; no new whitespace errors; only the intended staged/unstaged Task 3 files appear before commit.

- [ ] **Step 4: Commit the submodule and documentation update**

```powershell
git add -- overwrite/OpenClash_Overwrite rule/README.md
git commit --no-gpg-sign -m "docs: document custom rule ownership"
```

- [ ] **Step 5: Perform final post-commit verification**

Run:

```powershell
git status --porcelain=v1
git rev-list --left-right --count origin/main...HEAD
git log --oneline origin/main..HEAD
python -B py/validate_custom_rules.py
python -B -m unittest discover -s py -p 'test_*.py' -v
```

Expected: clean worktree; branch ahead only by the design/plan and three implementation commits; validator and all tests pass.

Do not push until the user explicitly requests publication.
