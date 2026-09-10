"""Collect change lists separately; export source cells without inventing events."""
import csv
import hashlib
import json
import re
import sys
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse
import openpyxl
from bs4 import BeautifulSoup
from .sources import BASE, REGIONS, compact, validate_month, month_tokens
from .storage import RawStore
from .workbooks import workbooks
from .monthly import write_json

EXTRA = {
 "hokkaido": ["/hokkaido/gyomu/gyomu/hoken_kikan/"+n+".html" for n in
              ("shinki_shitei_ichiran","haishi_ichiran","jitai_kikan_ichiran","toroku_torikeshi_ichiran","toroku_torikeshisoto_ichiran")],
 "tokai": ["/tokaihokuriku/newpage_00"+str(n)+".html" for n in (345,346,347,348)],
 "shikoku": ["/shikoku/gyomu/gyomu/hoken_kikan/shitei/shinki.html", "/shikoku/gyomu/gyomu/hoken_kikan/shitei/joutaibetsu.html"],
 "kinki": ["/kinki/tyousa/haishi.html"],
 "kyushu": ["/kyushu/tyosaka/20150407_00002.html","/kyushu/tyosaka/201504072_00001.html",
            "/kyushu/tyosaka/20150408_00001.html","/kyushu/gyomu/gyomu/hoken_kikan/index_00009.html"],
}
WORDS = "新規|廃止|辞退|取消|診療科.*変更"

def change_links(html, page, region, month):
    """month refers to processing/publication month, never an effective date."""
    soup=BeautifulSoup(html,"html.parser")
    year,m=map(int,month.split("-")); era=f"r{year-2018:02}{m:02}"
    # Kanto filename month is the following publication month.
    next_year,next_month=(year+1,1) if m==12 else (year,m+1)
    next_era=f"r{next_year-2018:02}{next_month:02}"
    results={}
    for a in soup.select("a[href]"):
        url=urljoin(page,a['href']);path=urlparse(url).path.lower()
        if urlparse(url).hostname!="kouseikyoku.mhlw.go.jp" or not path.endswith((".xlsx",".zip",".pdf",".xls")):continue
        heading=a.find_previous(["h1","h2","h3","h4"])
        head=compact(heading.get_text()) if heading else ""
        row=a.find_parent("tr");table=a.find_parent("table")
        label=compact(a.get_text());rowtext=compact(row.get_text()) if row else compact(a.parent.get_text())
        tabletext=compact(table.get_text()) if table else ""
        date_match=any(t in rowtext+head for t in month_tokens(month))
        context=head+rowtext
        selected=False
        if region=="tohoku":
            selected=bool(re.search(r"/(shitei|haishi|jitai|torikeshi)-[^/]*"+era+r"[^/]*\.(xlsx|zip|pdf)$",path)) and not re.search(r"-(ika|shika|yakkyoku)",path)
        elif region=="kanto":
            selected=bool(re.search(r"/(shinki|haishi|jitai|torikeshi)_"+next_era+r"[^/]*\.(xlsx|zip|pdf)$",path))
        elif region=="kinki":
            selected=f"{year}.{m}_" in path and bool(re.search(r"(sinki|haisi|haishi|jitai|torikeshi)",path))
        elif region=="kyushu":
            strong=a.find_previous("strong")
            dated=compact(strong.get_text()) if strong else ""
            selected=any(t in dated for t in month_tokens(month)) and bool(re.search(WORDS,dated+head))
        else:
            # Explicit nearby period and administrative list wording, never just a date in the whole page.
            selected=date_match and bool(re.search(WORDS,context+tabletext[:150]))
        if selected:
            results[url]={"source_url":url,"label":label,"context":context[:600],"region":region,"discovery_page":page,
                          "requested_processing_month":month,"event_type":"uninterpreted_source"}
    return list(results.values())

def extract_cells(source):
    body=Path(source['raw_file']).read_bytes()
    if hashlib.sha256(body).hexdigest()!=source['sha256']:raise ValueError('raw hash mismatch')
    if not urlparse(source['source_url']).path.lower().endswith(('.xlsx','.zip')):
        return [],'retained_needs_pdf_or_xls_adapter'
    records=[]
    for member,data in workbooks(body,Path(urlparse(source['source_url']).path).name):
        wb=openpyxl.load_workbook(BytesIO(data),read_only=True,data_only=True)
        try:
            for sheet in wb:
                sheet.reset_dimensions()
                for n,row in enumerate(sheet.iter_rows(values_only=True),1):
                    if n>600000:raise ValueError('row limit exceeded')
                    cells=[str(v) if v is not None else '' for v in row]
                    if not any(v.strip() for v in cells):continue
                    records.append(dict(source_url=source['source_url'],source_sha256=source['sha256'],
                        retrieved_at=source['retrieved_at'],requested_month=source['requested_processing_month'],
                        member=member,sheet=sheet.title,row=n,cells=cells,parser_version='change-cells/0.2'))
        finally:wb.close()
    return records,'cells_extracted_not_semantically_interpreted'

def collect_changes(month, output, regions=None):
    validate_month(month);regions=regions or list(REGIONS)
    if any(r not in REGIONS for r in regions):raise ValueError('unknown region')
    root=Path(output);run=root/'change-runs'/(month+'-'+uuid.uuid4().hex[:12]);run.mkdir(parents=True,exist_ok=False)
    store=RawStore(root/'raw');pages=[];sources=[];issues=[];seen=set();coverage=[]
    for region in regions:
        for path in [REGIONS[region][1]]+EXTRA.get(region,[]):
            page=BASE+path
            try:
                body,record=store.download(page,region=region,bureau=REGIONS[region][0],category='change_index',requested_processing_month=month)
                pages.append(record);links=change_links(body,page,region,month)
                coverage.append(dict(region=region,page=page,selected_links=len(links),status='links_found' if links else 'no_month_links_found_requires_review'))
                for link in links:
                    if link['source_url'] in seen:continue
                    seen.add(link['source_url'])
                    try:
                        _,item=store.download(link['source_url'],**{k:v for k,v in link.items() if k!='source_url'},
                            bureau=REGIONS[region][0],category='change',parser_version='change-cells/0.2',discovery_page_sha256=record['sha256'])
                        sources.append(item);write_json(run/'sources.json',sources)
                    except Exception as error:issues.append(dict(url=link['source_url'],error=str(error)))
            except Exception as error:issues.append(dict(url=page,error=str(error)))
            write_json(run/'pages.json',pages)
            print('change sources checked '+region+': '+page,file=sys.stderr,flush=True)
    count=0;results=[]
    with (run/'change-cells.csv').open('w',encoding='utf-8-sig',newline='') as out:
        fields=['source_url','source_sha256','retrieved_at','requested_month','member','sheet','row','cells','parser_version']
        writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
        for source in sources:
            try:
                records,status=extract_cells(source)
                for record in records:
                    record['cells']=json.dumps(record['cells'],ensure_ascii=False);writer.writerow(record);count+=1
                results.append(dict(url=source['source_url'],status=status,rows=len(records)))
            except Exception as error:issues.append(dict(url=source['source_url'],error=str(error)))
    write_json(run/'sources.json',sources)
    report=dict(run=str(run.resolve()),processing_month=month,status='review_required',sources=len(sources),rows=count,
        coverage=coverage,results=results,errors=issues,
        note='Source-cell CSV is staging data, not Event Items. No-month-links is not no changes. No effective dates are inferred.')
    write_json(run/'report.json',report)
    return report
