"""Validate a legacy JSON database; create a new SQLite file only with --apply."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile

from pypinyin import lazy_pinyin

spec = importlib.util.spec_from_file_location("sqlite_store", Path(__file__).resolve().parents[1] / "app/sqlite_store.py")
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


def repair_derived(data):
    categories = data.setdefault("categories", {})
    dates = data.setdefault("date", {})
    added = {"categories": 0, "date": 0}
    for blog in data.get("blogs", {}).values():
        for name, rows, fields in [("categories", categories, ("name",)), ("date", dates, ("year", "month"))]:
            expected = {"name": blog.get("category")} if name == "categories" else {"year": blog.get("year"), "month": blog.get("month")}
            if any(value is None for value in expected.values()):
                raise ValueError("Blog lacks a category or date; manual review required")
            matches = [row for row in rows.values() if all(row.get(key) == expected[key] for key in fields)]
            if len(matches) > 1:
                raise ValueError("Duplicate derived key; manual review required")
            if not matches:
                key = str(max(map(int, rows), default=0) + 1)
                rows[key] = expected
                if name == "categories":
                    rows[key]["html_title"] = "_".join(lazy_pinyin(expected["name"]))
                added[name] += 1
    for row in categories.values():
        row["num"] = sum(blog.get("category") == row.get("name") for blog in data.get("blogs", {}).values())
    for row in dates.values():
        row["num"] = sum((blog.get("year"), blog.get("month")) == (row.get("year"), row.get("month")) for blog in data.get("blogs", {}).values())
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repair-derived", action="store_true", help="Rebuild missing category/date records and their counts from articles")
    args = parser.parse_args()
    source, target = Path(args.source), Path(args.target)
    if target.exists():
        raise FileExistsError("Target already exists; refusing to overwrite")
    original = storage.read_documents(source)
    data = copy.deepcopy(original)
    added = repair_derived(data) if args.repair_derived else {}
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=target.parent)
    os.close(fd)
    try:
        storage.SQLiteStore(temporary).replace_all(data)
        migrated = storage.read_documents(temporary)
        if migrated != data:
            raise ValueError("Migration round-trip mismatch")
        for name, rows in original.items():
            if name not in ("categories", "date") and migrated[name] != rows:
                raise ValueError("Original records changed")
        if args.apply:
            # Hard-link creation is exclusive; an existing destination is never replaced.
            os.link(temporary, target)
        print(json.dumps({"applied": args.apply, "schema_version": storage.SCHEMA_VERSION, "table_counts": {key: len(value) for key, value in data.items()}, "added_derived_records": added}))
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
