"""Acquire monthly reports and export reviewable canonical files (no Wikibase writes)."""
import csv
import hashlib
import json
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from .core import convert_csv
from .sources import BASE, REGIONS, discover, validate_month
from .storage import RawStore, now
from .workbooks import PARSER_VERSION, parse_workbook, workbooks

FIELDS = ["insurance_id", "prefecture", "kind", "code", "name", "postal_code", "address", "phone",
          "opener_raw", "manager_raw", "designation_dates_raw", "beds_departments_raw", "status_raw",
          "secondary_codes_raw", "address_raw", "as_of", "source_url", "source_sha256", "retrieved_at",
          "parser_version", "member", "member_sha256", "sheet", "row_start", "row_end", "wikidata_qid"]
BUSINESS_FIELDS = [k for k in FIELDS if k not in {"source_url", "source_sha256", "retrieved_at", "parser_version",
    "member", "member_sha256", "sheet", "row_start", "row_end", "as_of", "wikidata_qid"}]

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8")

def jsonl(path, records):
    with path.open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, default=str)+"\n")

def business(record):
    return {k: record.get(k, "") for k in BUSINESS_FIELDS}

def reconcile(records):
    grouped = defaultdict(list)
    for record in records: grouped[record["insurance_id"]].append(record)
    accepted, conflicts = [], []
    for key in sorted(grouped):
        group = grouped[key]
        if len({json.dumps(business(r), sort_keys=True, ensure_ascii=False) for r in group}) != 1:
            conflicts.append(dict(insurance_id=key, reason="conflicting records for same insurance ID", records=group))
        else:
            row = group[0]
            row["provenance"] = [{k:r[k] for k in ("source_url","source_sha256","retrieved_at","member","member_sha256","sheet","row_start","row_end")} for r in group]
            accepted.append(row)
    return accepted, conflicts

def observed_diff(previous_path, current, comparable):
    if not comparable:
        return {"status":"not_comparable", "reason":"current coverage incomplete or conflicting"}
    previous_path = Path(previous_path)
    prior_report = json.loads((previous_path.parent / "report.json").read_text())
    if prior_report.get("status") != "complete":
        return {"status":"not_comparable", "reason":"previous coverage incomplete"}
    old = {r["insurance_id"]:r for r in map(json.loads, previous_path.read_text().splitlines())}
    new = {r["insurance_id"]:r for r in current}
    return {"status":"observed_only", "added":sorted(new.keys()-old.keys()),
        "missing":sorted(old.keys()-new.keys()),
        "changed":[{"insurance_id":k,"fields":{f:{"before":old[k].get(f),"after":new[k].get(f)}
            for f in BUSINESS_FIELDS if old[k].get(f)!=new[k].get(f)}}
            for k in sorted(old.keys() & new.keys()) if business(old[k])!=business(new[k])],
        "interpretation":"missing is not abolition; effective dates require an explicit source"}

def process(sources, run, month, regions, acquisition_errors=None, previous=None):
    records, diagnostics, source_results = [], [], []
    coverage = set()
    for source in sources:
        source = dict(source)
        try:
            body = Path(source["raw_file"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != source["sha256"]:
                raise ValueError("raw hash mismatch")
            file_records, file_diagnostics, file_coverage = [], [], set()
            for member, content in workbooks(body, Path(urlparse(source["source_url"]).path).name):
                if "併設" in member or "heiset" in member.lower():
                    file_diagnostics.append({"severity":"info","code":"supplementary_member_retained_in_raw","member":member})
                    continue
                parsed, issues, covered = parse_workbook(content, member, source["region"], month, source)
                file_records.extend(parsed); file_diagnostics.extend(issues)
                file_coverage.update((p,k) for p,k in covered)
            if not file_records: raise ValueError("no workbooks parsed")
            records.extend(file_records); diagnostics.extend(file_diagnostics); coverage.update(file_coverage)
            source_results.append({"source_url":source["source_url"],"status":"parsed","records":len(file_records),"verified_as_of":sorted({r["as_of"] for r in file_records}),"parser_version":PARSER_VERSION})
        except Exception as error:
            source_results.append({"source_url":source["source_url"],"status":"failed","error":str(error)})
        print(f"converted {source['region']}: {source_results[-1]['status']}", file=sys.stderr, flush=True)
    accepted, conflicts = reconcile(records)
    expected={(f"{p:02}",k) for region in regions for p in REGIONS[region][2] for k in ("医科","歯科","薬局")}
    missing = sorted(expected-coverage)
    errors = list(acquisition_errors or [])
    status = "complete" if accepted and not missing and not conflicts and not errors and all(r["status"]=="parsed" for r in source_results) else "incomplete"
    jsonl(run/"institutions.jsonl",accepted)
    jsonl(run/"conflicts.jsonl",conflicts)
    with (run/"institutions.csv").open("w",encoding="utf-8-sig",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS,extrasaction="ignore");writer.writeheader();writer.writerows(accepted)
    bundle = convert_csv(run/"institutions.csv", "jp-medical-registry")
    # Preserve complete source records independently of the minimal 0.1 bundle.
    bundle["provenance_manifest"]="sources.json"
    bundle["validation_status"]=status
    write_json(run/("bundle.json" if status=="complete" else "bundle.review.json"),bundle)
    report={"month":month,"regions":regions,"status":status,"parser_version":PARSER_VERSION,
        "created_at":now(),"raw_records":len(records),"institutions":len(accepted),
        "conflicting_identifiers":len(conflicts),"coverage":sorted(coverage),"missing_coverage":missing,
        "source_results":source_results,"acquisition_errors":errors,"diagnostics":diagnostics,
        "counts_by_prefecture_kind":dict(Counter(r["prefecture"]+"/"+r["kind"] for r in accepted)),
        "scope":"primary code-content snapshots; no inferred closures or Wikibase writes"}
    write_json(run/"report.json",report)
    if previous:
        prior=json.loads((Path(previous).parent/"report.json").read_text())
        same_scope=set(prior.get("regions",[]))==set(regions)
        y,m=map(int,month.split("-"))
        prior_month=f"{y-1}-12" if m==1 else f"{y}-{m-1:02}"
        same_scope = same_scope and prior.get("month") == prior_month
        write_json(run/"observed-diff.json",observed_diff(previous,accepted,status=="complete" and same_scope))
    return report

def collect(month, output, regions=None, previous=None):
    validate_month(month)
    regions=regions or list(REGIONS)
    if not regions or any(r not in REGIONS for r in regions): raise ValueError("unknown region")
    root=Path(output); root.mkdir(parents=True,exist_ok=True)
    run=root/"runs"/(month+"-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    store=RawStore(root/"raw")
    pages,sources,candidates,errors=[],[],[],[]
    for region in regions:
        print("discovering "+region,file=sys.stderr,flush=True)
        try:
            url=BASE+REGIONS[region][1]
            body,meta=store.download(url,region=region,bureau=REGIONS[region][0],requested_month=month,category="index")
            pages.append(meta)
            selected=discover(body,region,month)
            if not selected: raise ValueError("no snapshot links discovered for requested month")
            candidates.extend(selected)
            for item in selected:
                try:
                    _,source=store.download(item["url"],region=region,bureau=REGIONS[region][0],requested_month=month,
                        category=item["category"],discovery_page=url,discovery_page_sha256=meta["sha256"],
                        parser_version=PARSER_VERSION)
                    sources.append(source)
                    write_json(run/"sources.json",sources)
                    print("downloaded "+item["url"],file=sys.stderr,flush=True)
                except Exception as error: errors.append({"url":item["url"],"error":str(error)})
        except Exception as error: errors.append({"region":region,"error":str(error)})
        write_json(run/"pages.json",pages);write_json(run/"discovery.json",candidates);write_json(run/"acquisition-errors.json",errors)
    write_json(run/"sources.json",sources)
    report=process(sources,run,month,regions,errors,previous)
    return {"run":str(run.resolve()),**report}

def replay(manifest, month, output, regions=None, previous=None):
    validate_month(month)
    sources=json.loads(Path(manifest).read_text())
    regions=regions or sorted({s["region"] for s in sources})
    if any(r not in REGIONS for r in regions): raise ValueError("unknown region")
    run=Path(output);run.mkdir(parents=True,exist_ok=False)
    sources=[s for s in sources if s["region"] in regions]
    write_json(run/"sources.json",sources)
    report=process(sources,run,month,regions,previous=previous)
    return {"run":str(run.resolve()),**report}
