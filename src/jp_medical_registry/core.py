import csv
import hashlib
import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FEE_TYPES = {"医科": "1", "歯科": "3", "薬局": "4"}

def insurance_id(prefecture, kind, raw_code):
    if not re.fullmatch(r"\d{2}", prefecture, re.ASCII) or not 1 <= int(prefecture) <= 47:
        raise ValueError("prefecture must be 01..47")
    if kind not in FEE_TYPES:
        raise ValueError("kind must be 医科, 歯科 or 薬局")
    text = unicodedata.normalize("NFKC", raw_code).strip()
    # Never silently discard a secondary identifier or arbitrary text.
    if not re.fullmatch(r"[0-9,・.\-\s]+", text):
        raise ValueError("ambiguous code; split and review source identifiers first")
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) != 7:
        raise ValueError("regional code must contain exactly seven digits")
    return prefecture + FEE_TYPES[kind] + digits

def fetch(url, directory, bureau, period):
    if not url.startswith("https://"):
        raise ValueError("HTTPS source required")
    request = urllib.request.Request(url, headers={"User-Agent": "jp-medical-registry/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        final_url, media_type = response.url, response.headers.get_content_type()
    digest = hashlib.sha256(body).hexdigest()
    base = Path(directory); base.mkdir(parents=True, exist_ok=True)
    path = base / digest
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("existing raw file hash mismatch")
    else:
        with path.open("xb") as stream: stream.write(body)
    record = dict(source_url=url, final_url=final_url, bureau=bureau,
                  target_period=period, retrieved_at=datetime.now(timezone.utc).isoformat(),
                  sha256=digest, media_type=media_type, raw_file=digest,
                  parser_version="raw-fetch/0.1", publication_date=None)
    with (base / "observations.jsonl").open("a") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

def convert_csv(path, namespace):
    entities = []; seen = set()
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"prefecture", "kind", "code", "name", "source_url"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("missing canonical CSV columns")
        for row in reader:
            identifier = insurance_id(row["prefecture"], row["kind"], row["code"])
            if identifier in seen: raise ValueError("duplicate identifier: " + identifier)
            seen.add(identifier)
            if not row["name"].strip() or not row["source_url"].startswith("https://"):
                raise ValueError("name and HTTPS source URL are required")
            claims = [{"property": "P13179", "datatype": "external-id", "value": identifier},
                      {"property": "P1448", "datatype": "monolingualtext",
                       "value": {"language": "ja", "text": row["name"]}}]
            for claim in claims:
                claim["references"] = [[{"property": "P854", "datatype": "url", "value": row["source_url"]}]]
            qid = row.get("wikidata_qid", "")
            if qid and not re.fullmatch(r"Q[1-9][0-9]*", qid): raise ValueError("invalid QID")
            entities.append(dict(key=identifier, labels={"ja": row["name"]}, statements=claims,
                                 wikidata_qid=qid or None,
                                 raw={k: row[k] for k in required}))
    return {"schema_version": "0.1", "dataset": namespace, "entities": entities}

def diff(previous, current):
    old = {e["key"]: e for e in previous["entities"]}
    new = {e["key"]: e for e in current["entities"]}
    if previous["dataset"] != current["dataset"]: raise ValueError("different datasets")
    return {"added": sorted(new.keys()-old.keys()), "missing": sorted(old.keys()-new.keys()),
            "changed": sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
            "interpretation": "observed differences; missing is not closure; effective dates unknown"}
