#!/usr/bin/env python3
"""Public Open Startup Deals snapshot: strict allowlist and fail-closed validation.

Export is intentionally offline: the private site must be read by an authorized
caller. Never give GitHub Actions a private-site session or service token.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

FIELDS = (
    "id", "name", "org", "category", "country", "audience", "stage",
    "eligibility", "requirements", "value", "amount", "currency",
    "validity", "deadline", "status", "confidence", "official",
    "evidence", "verified",
)
REQUIRED = ("id", "name", "org", "official")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SECRETS_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}"
    r"|Bearer\s+[A-Za-z0-9._~-]{12,}|api[_ -]?key\s*[:=]\s*\S{8,}"
    r"|password\s*[:=]\s*\S{8,}|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY)"
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?55[\s().-]*)?\(?\d{2}\)?[\s().-]*9\d{4}[\s().-]*\d{4}(?!\d)")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso_time(value):
    if not isinstance(value, str):
        raise ValueError("snapshot_at must be an ISO 8601 string")
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("snapshot_at is not valid ISO 8601") from exc
    if ts.tzinfo is None:
        raise ValueError("snapshot_at must contain a timezone")
    return ts.astimezone(dt.timezone.utc)


def items_from(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for name in ("deals", "opportunities", "records", "items", "catalog"):
            if isinstance(raw.get(name), list):
                return raw[name]
        for name in ("data", "result"):
            inner = raw.get(name)
            if isinstance(inner, (dict, list)):
                return items_from(inner)
    raise ValueError("No complete array of offers found; refusing to publish")


def checked_url(value):
    if not isinstance(value, str):
        raise ValueError("official URL must be a string")
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ValueError("official URL must be a public HTTPS URL")
    if parts.query:
        allowed = {"var", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if not pairs or any(k not in allowed or len(v) > 80 or not re.fullmatch(r"[A-Za-z0-9_.~-]*", v) for k, v in pairs):
            raise ValueError("official URL has unsafe query parameters")
    if parts.fragment:
        raise ValueError("official URL has a fragment; verify before exporting")
    if "@" in parts.netloc:
        raise ValueError("official URL contains authentication")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def check_public_text(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > 10000:
        raise ValueError(f"{field} too long for public export")
    if EMAIL_RE.search(value) or SECRETS_RE.search(value) or PHONE_RE.search(value):
        raise ValueError(f"{field} contains possible private data; publication blocked")
    return value


def sanitize_one(item):
    if not isinstance(item, dict):
        raise ValueError("Each offer must be an object")
    out = {}
    for field in FIELDS:
        if field not in item or item[field] is None:
            continue
        value = item[field]
        if field == "official":
            value = checked_url(value)
        elif field == "audience":
            if not isinstance(value, list) or len(value) > 100 or not all(isinstance(v, str) for v in value):
                raise ValueError("audience must be a list of strings")
            value = [check_public_text(v, f"audience[{i}]") for i, v in enumerate(value)]
        elif field == "amount":
            if isinstance(value, bool) or not isinstance(value, (float, int)):
                raise ValueError("amount must be numeric or null")
        else:
            value = check_public_text(value, field)
        out[field] = value
    for field in REQUIRED:
        if not out.get(field):
            raise ValueError(f"Missing public field: {field}")
    if not ID_RE.fullmatch(out["id"]):
        raise ValueError(f"Invalid ID: {out['id']!r}")
    return out


def validate_deals(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty or non-list catalog; refusing to publish")
    ids = set()
    output = []
    for raw in rows:
        row = sanitize_one(raw)
        if row["id"] in ids:
            raise ValueError("Duplicate offer id: " + row["id"])
        ids.add(row["id"])
        output.append(row)
    return sorted(output, key=lambda v: v["id"])


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_export(args):
    fresh = validate_deals(items_from(read_json(args.input)))
    old = read_json(args.previous) if args.previous and Path(args.previous).exists() else None
    if old:
        old_rows = validate_deals(items_from(old))
        old_ids = {r["id"] for r in old_rows}
        new_ids = {r["id"] for r in fresh}
        overlap = len(old_ids & new_ids) / len(old_ids)
        if overlap < args.min_retention:
            raise ValueError(
                f"Only {overlap:.0%} of previous IDs retained; possibly partial export"
            )
        if len(fresh) < len(old_rows) and not args.allow_shrink:
            raise ValueError("Catalog smaller than previous public snapshot; review manually")
    timestamp = iso_time(args.collected_at) if args.collected_at else utcnow()
    if timestamp > utcnow() + dt.timedelta(minutes=5):
        raise ValueError("Collection timestamp is in the future")
    out = {
        "schema_version": (old.get("schema_version", 1) if old else 1),
        "snapshot_at": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "verification_note": (
            "Data da captura do catálogo público em UTC. 'verified' é a data "
            "da verificação de cada oferta. Créditos anunciados não significam "
            "candidatura aprovada, saldo concedido ou elegibilidade individual."
        ),
        "record_count": len(fresh),
        "license": (
            old.get("license", {"id": "ODC-By-1.0", "url": "https://opendatacommons.org/licenses/by/1-0/"})
            if old else {"id": "ODC-By-1.0", "url": "https://opendatacommons.org/licenses/by/1-0/"}
        ),
        "deals": fresh,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"EXPORTED {len(fresh)} public rows at {out['snapshot_at']}")


def run_check(args):
    doc = read_json(args.input)
    rows = validate_deals(items_from(doc))
    if doc.get("record_count") != len(rows):
        raise ValueError("record_count disagrees with actual number of offers")
    ts = iso_time(doc.get("snapshot_at"))
    age = (utcnow() - ts).total_seconds() / 3600
    if age < -0.1:
        raise ValueError("snapshot_at lies in the future")
    if args.max_age_hours is not None and age > args.max_age_hours:
        raise ValueError(f"Public snapshot STALE: age={age:.2f}h, limit={args.max_age_hours}h")
    print(f"VALIDATED {len(rows)} offers; age={age:.2f} hours")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    exp = sub.add_parser("export", help="Build an allowlisted public snapshot from authorized private JSON")
    exp.add_argument("--input", required=True)
    exp.add_argument("--output", default="data/deals.json")
    exp.add_argument("--previous", default="data/deals.json")
    exp.add_argument("--min-retention", type=float, default=0.8)
    exp.add_argument("--allow-shrink", action="store_true")
    exp.add_argument("--collected-at", help="ISO 8601 time recorded AFTER a successful private read")
    chk = sub.add_parser("check", help="Validate an existing public snapshot")
    chk.add_argument("--input", default="data/deals.json")
    chk.add_argument("--max-age-hours", type=float)
    args = parser.parse_args()
    try:
        if args.mode == "export":
            run_export(args)
        else:
            run_check(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("PUBLICATION BLOCKED:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
