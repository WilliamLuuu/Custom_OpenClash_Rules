import os
import subprocess
import sys
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

    def test_rejects_unexpected_third_domain_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.list"
            source.write_text("DOMAIN,example.com,no-resolve\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly 2 fields"):
                validate_custom_rules.parse_rule_file(source)

    def test_rejects_invalid_ip_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.list"
            source.write_text("IP-CIDR,192.0.2.0/24,unknown\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid IP attribute"):
                validate_custom_rules.parse_rule_file(source)

    def test_accepts_ip_no_resolve_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "ok.list"
            source.write_text("IP-CIDR,192.0.2.0/24,no-resolve\n", encoding="utf-8")
            records = validate_custom_rules.parse_rule_file(source)
        self.assertEqual(records[0].rule_type, "IP-CIDR")
        self.assertEqual(records[0].value, "192.0.2.0/24")


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

    def test_reports_merge_conflict_markers_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rule").mkdir()
            (root / "cfg").mkdir()
            (root / "cfg" / "Custom_Clash.ini").write_text(
                ";Custom_OpenClash_Rules\n[custom]\n"
                "<<<<<<< HEAD\n=======\n>>>>>>> topic\n",
                encoding="utf-8",
            )
            errors = validate_custom_rules.validate_repository(
                root,
                custom_rule_files=(),
                direct_files=(),
                proxy_files=(),
            )
        self.assertEqual(
            [error for error in errors if "merge conflict marker" in error],
            [
                "cfg/Custom_Clash.ini:3: merge conflict marker: <<<<<<< HEAD",
                "cfg/Custom_Clash.ini:4: merge conflict marker: =======",
                "cfg/Custom_Clash.ini:5: merge conflict marker: >>>>>>> topic",
            ],
        )


class CliTests(unittest.TestCase):
    def test_reports_unicode_errors_without_traceback_in_gbk_console(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rule").mkdir()
            (root / "cfg").mkdir()
            (root / "cfg" / "Custom_Clash.ini").write_text(
                ";Custom_OpenClash_Rules\n[custom]\n"
                "custom_proxy_group=Proxy`select`[]🇬🇧 英国节点\n",
                encoding="utf-8",
            )
            environment = os.environ | {"PYTHONIOENCODING": "gbk"}
            result = subprocess.run(
                [sys.executable, validate_custom_rules.__file__, "--root", str(root)],
                capture_output=True,
                env=environment,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("undefined proxy group", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


class LiveRepositoryValidationTests(unittest.TestCase):
    def test_repository_custom_rules_are_valid(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(validate_custom_rules.validate_repository(root), [])


if __name__ == "__main__":
    unittest.main()
