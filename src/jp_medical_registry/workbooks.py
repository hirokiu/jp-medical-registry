"""Parse code-content printed Excel reports, retaining complete record cells."""
import hashlib
import re
import unicodedata
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
import openpyxl
from .core import insurance_id
from .sources import REGIONS, compact

PARSER_VERSION = "code-content-xlsx/0.2"
PREFECTURES = "北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄".split()

class LayoutError(ValueError):
    pass

def workbooks(body, filename):
    if not zipfile.is_zipfile(BytesIO(body)):
        raise LayoutError("unsupported non-XLSX/ZIP input; PDF/XLS need another adapter")
    with zipfile.ZipFile(BytesIO(body)) as archive:
        if "xl/workbook.xml" in archive.namelist():
            yield filename, body
            return
        members = [i for i in archive.infolist() if not i.is_dir()]
        if sum(i.file_size for i in members) > 512 * 1024 * 1024 or len(members) > 500:
            raise LayoutError("archive exceeds size/member limit")
        for info in members:
            normalized = info.filename.replace("\\", "/")
            if normalized.endswith("/"):
                continue
            if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
                raise LayoutError("unsafe archive member")
            if normalized.lower().endswith(".xlsx"):
                yield normalized, archive.read(info)
            elif not normalized.startswith("__MACOSX/") and not normalized.endswith(".DS_Store"):
                raise LayoutError("unsupported archive member: " + normalized)

def norm(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()

def parse_workbook(data, member, region, month, source):
    wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
    records, diagnostics, coverage = [], [], []
    try:
        for sheet in wb:
            sheet.reset_dimensions()  # Official workbooks may incorrectly declare A1 only.
            iterator = sheet.iter_rows(values_only=True)
            rows = []
            for index, row in enumerate(iterator, 1):
                if index > 600000:
                    raise LayoutError("sheet row limit exceeded")
                rows.append((index, [str(v) if v is not None else "" for v in row]))
            nonempty = [(i,r) for i,r in rows if any(v.strip() for v in r)]
            if not nonempty:
                continue
            header = " ".join(" ".join(r[:3]) for _,r in nonempty[:15])
            if "コード内容別" not in header:
                raise LayoutError(f"unrecognized snapshot layout: {member}:{sheet.title}")
            dates = re.findall(r"令和\s*(\d+)年\s*(\d+)月\s*(\d+)日現在", norm(header))
            if not dates:
                raise LayoutError("missing as-of date")
            periods = {f"{int(y)+2018:04}-{int(m):02}" for y,m,d in dates}
            if periods != {month}:
                raise LayoutError("snapshot month mismatch: " + str(periods))
            kind_match = re.search(r"日現在\s*(医科|歯科|薬局)", norm(header))
            if not kind_match:
                raise LayoutError("missing institution kind")
            kind = kind_match[1]
            if re.search(r"日現在\s*(?:医科|歯科)併設", norm(header)) or "heiset" in member.lower() or "併設" in member:
                raise LayoutError("supplementary designation layout requires separate review")
            # Prefer bracketed prefecture in the printed header, then workbook/sheet name.
            bracketed = " ".join(re.findall(r"\[([^\]]+)\]", norm(header)))
            candidates = [i+1 for i,n in enumerate(PREFECTURES) if n in bracketed and i+1 in REGIONS[region][2]]
            if not candidates:
                candidates = [i+1 for i,n in enumerate(PREFECTURES) if n in member+sheet.title and i+1 in REGIONS[region][2]]
            if region == "hokkaido": candidates = [1]
            if len(set(candidates)) != 1:
                raise LayoutError("ambiguous prefecture: " + member + ":" + sheet.title)
            pref = f"{candidates[0]:02}"
            coverage.append([pref, kind])
            current = None
            def finish():
                if current is None: return
                rawrows = current.pop("_rows")
                first = rawrows[0][1]
                identifier = insurance_id(pref, kind, first[1])
                lines = lambda col: [r[col] for _,r in rawrows if len(r)>col and r[col].strip()]
                name = "".join(lines(2)).strip()
                address_raw = "".join(lines(3)).strip()
                postal = re.match(r"^〒?\s*(\d{3})[-ー−―‐－\s]?(\d{4})(.*)$", norm(address_raw), re.S)
                postal_code = postal[1]+"-"+postal[2] if postal else ""
                address = postal[3].strip() if postal else norm(address_raw)
                if not name: raise LayoutError("empty institution name")
                record = dict(prefecture=pref,kind=kind,code=re.sub(r"\D","",norm(first[1])),
                    insurance_id=identifier,name=name,postal_code=postal_code,address=address,
                    phone=norm(first[4]),opener_raw="\n".join(lines(5)),manager_raw="\n".join(lines(6)),
                    designation_dates_raw="\n".join(lines(7)),beds_departments_raw="\n".join(lines(8)),
                    status_raw="\n".join(lines(9)),secondary_codes_raw="\n".join(lines(1)[1:]),
                    address_raw=address_raw,as_of=f"{int(dates[0][0])+2018:04}-{int(dates[0][1]):02}-{int(dates[0][2]):02}",
                    source_url=source["source_url"],source_sha256=source["sha256"],
                    retrieved_at=source["retrieved_at"],parser_version=PARSER_VERSION,
                    member=member,member_sha256=hashlib.sha256(data).hexdigest(),sheet=sheet.title,
                    row_start=rawrows[0][0],row_end=rawrows[-1][0],wikidata_qid="",
                    raw_rows=[{"row":i,"cells":r} for i,r in rawrows])
                if not postal: diagnostics.append(dict(severity="warning",code="postal_unparsed",institution=identifier))
                records.append(record)
            for index, r in nonempty:
                r += [""] * max(0, 10-len(r))
                serial, code = norm(r[0]), norm(r[1])
                if re.fullmatch(r"[0-9]+",serial) and code:
                    finish()
                    try: insurance_id(pref,kind,code)
                    except ValueError as error: raise LayoutError(f"invalid numbered row {member}:{sheet.title}:{index}: {error}") from error
                    current = {"_rows": [(index,r)]}
                elif ("コード内容別" in r[0] or "日現在" in r[0] or "抽出条件" in r[0]
                      or "項番" in r[0] or "医療機関番号" in "".join(r) or "総件数" in "".join(r)):
                    continue
                elif current is not None:
                    # Header/footer fields are retained if not confidently identified.
                    current["_rows"].append((index,r))
            finish()
    finally:
        wb.close()
    if not records:
        raise LayoutError("no institution records found")
    return records, diagnostics, coverage
