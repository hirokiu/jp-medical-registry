import argparse
import json
from .core import insurance_id, fetch, convert_csv, diff

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    c=sub.add_parser("code"); c.add_argument("prefecture"); c.add_argument("kind"); c.add_argument("raw_code")
    c=sub.add_parser("fetch"); c.add_argument("url"); c.add_argument("directory"); c.add_argument("--bureau",required=True); c.add_argument("--period",required=True)
    c=sub.add_parser("convert-csv"); c.add_argument("path"); c.add_argument("--dataset",default="jp-medical-registry")
    c=sub.add_parser("diff"); c.add_argument("previous"); c.add_argument("current")
    a=p.parse_args()
    if a.command=="code": result=insurance_id(a.prefecture,a.kind,a.raw_code)
    elif a.command=="fetch": result=fetch(a.url,a.directory,a.bureau,a.period)
    elif a.command=="convert-csv": result=convert_csv(a.path,a.dataset)
    else:
        with open(a.previous) as f: old=json.load(f)
        with open(a.current) as f: new=json.load(f)
        result=diff(old,new)
    print(json.dumps(result,ensure_ascii=False,indent=2))
