import hashlib
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from jp_medical_registry.storage import RawStore
from jp_medical_registry.sources import discover
from jp_medical_registry.workbooks import parse_workbook, workbooks, LayoutError
from jp_medical_registry.monthly import reconcile, observed_diff, process
from jp_medical_registry.changes import change_links


def fixture(kind='医科', month=9):
    wb=Workbook(); s=wb.active; s.title='東京'
    s.append(['コード内容別医療機関一覧表','[東京都]'])
    s.append([f'[令和8年{month}月1日現在 {kind} 現存/休止]'])
    s.append(['1','02,7075,1','テスト病院','〒104－8560中央区明石町９番１号','03-3541-5151','開設者','管理者','昭和1年1月1日','一般 20','病院'])
    s.append(['','(02,9999,9)','','','常勤 10','','','','内 外','現存'])
    s.append(['2','02,1234,5','テスト診療所','〒100-0001東京都千代田区','03-1111-2222','','','','内','診療所'])
    s.append(['','','','','非常勤 1','','','','','休止'])
    out=BytesIO();wb.save(out);return out.getvalue()


def source(body):
    return {'source_url':'https://kouseikyoku.mhlw.go.jp/example.xlsx','sha256':hashlib.sha256(body).hexdigest(),'retrieved_at':'2026-09-10T00:00:00Z','region':'kanto'}

class ParserTests(unittest.TestCase):
    def test_multiline_and_secondary_identifier(self):
        b=fixture(); records,_,coverage=parse_workbook(b,'東京.xlsx','kanto','2026-09',source(b))
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['insurance_id'],'1310270751')
        self.assertEqual(records[0]['postal_code'],'104-8560')
        self.assertEqual(records[0]['phone'],'03-3541-5151')
        self.assertEqual(records[0]['secondary_codes_raw'],'(02,9999,9)')
        self.assertEqual(records[0]['beds_departments_raw'],'一般 20\n内 外')
        self.assertIn('休止',records[1]['status_raw'])
        self.assertEqual(coverage,[['13','医科']])

    def test_month_mismatch_rejected(self):
        b=fixture(month=8)
        with self.assertRaises(LayoutError):parse_workbook(b,'東京.xlsx','kanto','2026-09',source(b))

    def test_incorrect_dimension(self):
        import re
        b=fixture(); out=BytesIO()
        with zipfile.ZipFile(BytesIO(b)) as z, zipfile.ZipFile(out,'w') as dest:
            for name in z.namelist():
                data=z.read(name)
                if name=='xl/worksheets/sheet1.xml': data=re.sub(rb'<dimension ref="[^"]+"',b'<dimension ref="A1"',data)
                dest.writestr(name,data)
        records,_,_=parse_workbook(out.getvalue(),'東京.xlsx','kanto','2026-09',source(b))
        self.assertEqual(len(records),2)

    def test_windows_zip_paths_and_unsafe_paths(self):
        out=BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('folder\\',b'');z.writestr('folder\\東京.xlsx',fixture())
        self.assertEqual(list(workbooks(out.getvalue(),'sample.zip'))[0][0],'folder/東京.xlsx')
        out=BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('../evil.xlsx',fixture())
        with self.assertRaises(LayoutError):list(workbooks(out.getvalue(),'bad.zip'))

    def test_conflict_quarantined(self):
        b=fixture(); records,_,_=parse_workbook(b,'東京.xlsx','kanto','2026-09',source(b))
        other=dict(records[0],name='別の施設')
        accepted,conflicts=reconcile(records+[other])
        self.assertEqual(len(accepted),1);self.assertEqual(len(conflicts),1)

    def test_incomplete_run_does_not_produce_import_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); b=fixture(); raw=root/'raw.xlsx';raw.write_bytes(b)
            s={**source(b),'raw_file':str(raw)}
            result=process([s],root,'2026-09',['kanto'])
            self.assertEqual(result['status'],'incomplete')
            self.assertFalse((root/'bundle.json').exists())
            self.assertTrue((root/'bundle.review.json').exists())

class DiscoveryTests(unittest.TestCase):
    def test_excludes_other_month_and_supplement(self):
        h=''.join(f'<a href="/kantoshinetsu/{n}">ZIP</a>' for n in ['shitei_ika_r0809.zip','shitei_ika_r0808.zip','shitei_shikaheisetsu_r0809.zip'])
        self.assertEqual(len(discover(h,'kanto','2026-09')),1)

    def test_excludes_nursing_reports(self):
        h='<h2>コード内容別医療機関一覧 令和8年9月1日現在</h2><a href="a.zip">医科</a><h2>コード内容別訪問看護事業所一覧 令和8年9月1日現在</h2><a href="b.zip">看護</a>'
        self.assertEqual(len(discover(h,'chugoku','2026-09')),1)

    def test_processing_month_not_filename_month(self):
        h='<a href="/kantoshinetsu/haishi_r0809.zip">廃止</a><a href="/kantoshinetsu/haishi_r0808.zip">廃止</a>'
        links=change_links(h,'https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html','kanto','2026-08')
        self.assertEqual(len(links),1);self.assertTrue(links[0]['source_url'].endswith('r0809.zip'))

class StorageTests(unittest.TestCase):
    def test_same_url_new_contents_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            store=RawStore(d);a=store.save(b'old',{'source_url':'https://example.org/a'});b=store.save(b'new',{'source_url':'https://example.org/a'})
            self.assertNotEqual(a['sha256'],b['sha256'])
            self.assertEqual(Path(a['raw_file']).read_bytes(),b'old')
            self.assertEqual(store.save(b'old',{})['raw_file'],a['raw_file'])

    def test_provenance_only_not_business_change(self):
        a={'insurance_id':'1','name':'A','source_sha256':'old'};b={**a,'source_sha256':'new'}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'institutions.jsonl';p.write_text(json.dumps(a)+'\n')
            (p.parent/'report.json').write_text(json.dumps({'status':'complete'}))
            self.assertEqual(observed_diff(p,[b],True)['changed'],[])
            self.assertEqual(observed_diff(p,[],False)['status'],'not_comparable')

class ExportTests(unittest.TestCase):
    def test_address_phone_and_postal_claims(self):
        from jp_medical_registry.core import convert_csv
        import csv
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.csv'
            row={'prefecture':'13','kind':'医科','code':'0270751','name':'例','source_url':'https://example.org/source','postal_code':'104-8560','address':'中央区','phone':'03-3541-5151'}
            with p.open('w',newline='') as out:
                w=csv.DictWriter(out,fieldnames=list(row));w.writeheader();w.writerow(row)
            claims=convert_csv(p,'demo')['entities'][0]['statements']
            values={s['property']:s['value'] for s in claims}
            self.assertEqual(values['P281'],'104-8560')
            self.assertEqual(values['P1329'],'+81335415151')
            self.assertEqual(values['P6375'],{'language':'ja','text':'中央区'})
            self.assertTrue(all(s['references'][0][0]['property']=='P854' for s in claims))

    def test_change_csv_is_staging_and_keeps_request_month(self):
        from jp_medical_registry.changes import extract_cells
        with tempfile.TemporaryDirectory() as d:
            b=fixture();p=Path(d)/'source.xlsx';p.write_bytes(b)
            records,status=extract_cells({**source(b),'raw_file':str(p),'requested_processing_month':'2026-08'})
            self.assertTrue(records)
            self.assertEqual(records[0]['requested_month'],'2026-08')
            self.assertNotIn('effective_date',records[0])
            self.assertIn('not_semantically_interpreted',status)
