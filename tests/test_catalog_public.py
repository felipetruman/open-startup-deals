"""Regression tests for public catalog safety and completeness."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import catalog_public as pub  # noqa: E402


def row(offer_id):
    return {
        "id": offer_id, "name": "Demo", "org": "Demo Ltd",
        "official": "https://example.com/startups",
        "country": "Brasil", "amount": 1000,
        "audience": ["Startups", "Solo founder"],
        "evidence": "Página oficial verificada.",
    }


class PublicCatalogTests(unittest.TestCase):
    def test_public_allowlist_drops_private_fields(self):
        item = row("a")
        item.update({
            "application": {"notes": "confidential"},
            "history": [{"comments": "confidential"}],
            "phone": "+55 45 99902-2026",
            "api_key": "SECRET",
        })
        safe = pub.sanitize_one(item)
        self.assertEqual(safe["id"], "a")
        self.assertEqual(set(safe), set(row("a")))
        self.assertFalse(any(k in safe for k in ("history", "application", "phone", "api_key")))

    def test_email_in_public_fields_blocks_export(self):
        item = row("a")
        item["evidence"] = "Contato: user@example.com"
        with self.assertRaises(ValueError):
            pub.sanitize_one(item)

    def test_phone_in_public_fields_blocks_export(self):
        item = row("a")
        item["requirements"] = "+55 45 99902-2026"
        with self.assertRaises(ValueError):
            pub.sanitize_one(item)

    def test_api_secret_in_public_fields_blocks_export(self):
        item = row("a")
        item["requirements"] = "api_key = abcdefghijklmnopqrst"
        with self.assertRaises(ValueError):
            pub.sanitize_one(item)

    def test_official_must_not_contain_secrets_in_query(self):
        item = row("a")
        item["official"] += "?token=confidential"
        with self.assertRaises(ValueError):
            pub.sanitize_one(item)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            pub.validate_deals([row("a"), row("a")])

    def test_export_retains_previous_ids_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous.json"
            source = root / "private.json"
            output = root / "output.json"
            previous.write_text(json.dumps({"deals": [row("a"), row("b")]}), encoding="utf-8")
            new = [row("a"), row("b"), row("c")]
            new[0]["documents"] = ["private.pdf"]
            source.write_text(json.dumps({"records": new}), encoding="utf-8")
            args = type("Args", (), {
                "input": str(source), "output": str(output),
                "previous": str(previous), "min_retention": 0.8,
                "allow_shrink": False, "collected_at": None,
            })()
            pub.run_export(args)
            doc = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(doc["record_count"], 3)
            self.assertNotIn("documents", doc["deals"][0])
            self.assertTrue(doc["snapshot_at"].endswith("Z"))

    def test_partial_export_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous.json"
            source = root / "private.json"
            output = root / "output.json"
            previous.write_text(json.dumps({"deals": [row("a"), row("b"), row("c")]}), encoding="utf-8")
            source.write_text(json.dumps({"deals": [row("a")]}), encoding="utf-8")
            args = type("Args", (), {
                "input": str(source), "output": str(output),
                "previous": str(previous), "min_retention": 0.8,
                "allow_shrink": False, "collected_at": None,
            })()
            with self.assertRaises(ValueError):
                pub.run_export(args)
            self.assertFalse(output.exists())

    def test_expired_snapshot_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "snapshot.json"
            old_time = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
            file.write_text(json.dumps({
                "snapshot_at": old_time, "record_count": 1, "deals": [row("a")],
            }), encoding="utf-8")
            args = type("Args", (), {"input": str(file), "max_age_hours": 13.0})()
            with self.assertRaises(ValueError):
                pub.run_check(args)


if __name__ == "__main__":
    unittest.main()
