"""Verify downloaded baselines and render the recovered site without a server."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tarfile
from unittest.mock import patch
from urllib.parse import quote


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    destination = directory / "extracted"
    destination.mkdir(exist_ok=False)
    verified = 0
    for item in json.loads(Path(args.receipt).read_text(encoding="utf-8")):
        filename = item["filename"]
        if Path(filename).name != filename:
            raise ValueError("Invalid archive filename")
        archive_path = directory / filename
        if archive_path.stat().st_size != item["size"] or digest(archive_path) != item["sha256"]:
            raise ValueError("Archive checksum mismatch: " + filename)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(destination, filter="data")
    for folder in [destination / "full", destination / "content-history"]:
        manifest = json.loads((folder / "BACKUP-MANIFEST.json").read_text(encoding="utf-8"))
        for relative, entry in manifest.items():
            path = (folder / relative).resolve()
            if not path.is_relative_to(folder) or path.stat().st_size != entry["size"] or digest(path) != entry["sha256"]:
                raise ValueError("File checksum mismatch")
            verified += 1
    history = destination / "content-history"
    entries = json.loads((history / "manifest.json").read_text(encoding="utf-8"))
    for entry in entries:
        snapshot = history / Path(entry["path"]).name
        if digest(snapshot) != entry["sha256"]:
            raise ValueError("Historical snapshot hash mismatch")
        json.loads(snapshot.read_text(encoding="utf-8"))
    app_root = destination / "full/app"
    db_path = app_root / "db/blog_db.json"
    database = json.loads(db_path.read_text(encoding="utf-8"))
    os.environ.update({
        "BLOG_DB_PATH": str(db_path),
        "BLOG_ENV": "development",
        "BLOG_SECRET_KEY": secrets.token_hex(32),
        "BLOG_AMAP_WEB_SERVICE_KEY": "disabled-for-recovery-test",
        "BLOG_CONTENT_HISTORY_DIR": str(directory / "test-history"),
    })
    for kind, key in [("covers", "BLOG_COVER_UPLOAD_DIR"), ("articles", "BLOG_ARTICLE_IMAGE_UPLOAD_DIR"), ("diaries", "BLOG_DIARY_IMAGE_UPLOAD_DIR")]:
        os.environ[key] = str(app_root / "instance/uploads" / kind)
    sys.path.insert(0, str(app_root))
    with patch("socket.create_connection", side_effect=RuntimeError("Network disabled in recovery test")):
        from app import create_app, blog_db
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with client.session_transaction() as session:
            session["admin_authenticated"] = True
        urls = ["/", "/diary", "/manage", "/manage/views"]
        for row in database.get("blogs", {}).values():
            urls.append("/{}/{}/{}".format(int(row["year"]), int(row["month"]), quote(row["html_title"])))
        for row in database.get("diaries", {}).values():
            year, month, day = map(int, row["entry_date"].split("-"))
            urls.append("/diary/{}/{}/{}".format(year, month, day))
        image_count = 0
        for kind in ["covers", "articles", "diaries"]:
            root = app_root / "instance/uploads" / kind
            for path in root.rglob("*"):
                if path.is_file():
                    url = "/media/" + kind + "/" + quote(path.relative_to(root).as_posix())
                    response = client.get(url)
                    if response.status_code != 200 or response.data != path.read_bytes():
                        raise RuntimeError("Restored image response mismatch")
                    response.close()
                    image_count += 1
        for url in urls:
            response = client.get(url)
            if response.status_code != 200:
                raise RuntimeError("Restored page failed with HTTP " + str(response.status_code))
            response.close()
        blog_db.close()
    result = {"verified_files": verified, "historical_snapshots": len(entries), "rendered_pages": len(urls), "verified_upload_responses": image_count, "table_counts": {key: len(value) for key, value in database.items()}}
    (directory / "verification-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
