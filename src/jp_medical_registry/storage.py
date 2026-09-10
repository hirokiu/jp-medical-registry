"""Content-addressed raw files and append-only acquisition records."""
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

MAX_BYTES = 128 * 1024 * 1024

def now():
    return datetime.now(timezone.utc).isoformat()

class RawStore:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)

    def save(self, body, metadata):
        digest = hashlib.sha256(body).hexdigest()
        target = self.root / "objects" / digest
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("raw store corruption: " + digest)
        else:
            fd, temporary = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(body); out.flush(); os.fsync(out.fileno())
                try:
                    os.link(temporary, target)  # Never overwrite another acquisition.
                except FileExistsError:
                    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                        raise ValueError("raw store corruption")
            finally:
                os.unlink(temporary)
        record = {**metadata, "sha256": digest, "bytes": len(body),
                  "raw_file": str(target.resolve())}
        return record

    def download(self, url, **metadata):
        if not url.startswith("https://"):
            raise ValueError("HTTPS source required")
        request = urllib.request.Request(url, headers={"User-Agent": "jp-medical-registry/0.2 (+https://github.com/hirokiu/jp-medical-registry)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    if not response.url.startswith("https://"):
                        raise ValueError("HTTPS redirect required")
                    body = response.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise ValueError("source exceeds 128 MiB")
                    record = self.save(body, {**metadata, "source_url": url,
                        "final_url": response.url, "retrieved_at": now(),
                        "media_type": response.headers.get_content_type(),
                        "http_etag": response.headers.get("ETag"),
                        "http_last_modified": response.headers.get("Last-Modified"),
                        "publication_date": None, "file_format": Path(urlparse(response.url).path).suffix.lstrip(".") or "html", "acquisition_version": "https/0.2"})
                    return body, record
            except (urllib.error.URLError, TimeoutError) as error:
                if isinstance(error, urllib.error.HTTPError) and error.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")
