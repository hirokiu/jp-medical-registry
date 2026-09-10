"""Attach conservative decisions from a reviewed candidate file to a CSV bundle."""
import argparse
import csv
import json
from pathlib import Path
from .core import convert_csv
from .matching import assess

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv',type=Path)
    parser.add_argument('candidates',type=Path,help='JSON map: 10-digit institution code -> list of Wikidata entity objects')
    parser.add_argument('--dataset',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    candidates=json.loads(args.candidates.read_text())
    with args.csv.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    bundle=convert_csv(args.csv,args.dataset)
    records={r['insurance_id']:r for r in rows}
    for entity in bundle['entities']:
        decision=assess(records[entity['key']],candidates.get(entity['key'],[]))
        entity['wikidata_qid']=decision['qid']
        entity['match_decision']=decision
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(bundle,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
