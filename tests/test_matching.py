import copy
import unittest
from jp_medical_registry.matching import assess

class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.row={'insurance_id':'0110114386','name':'ＪＲ札幌病院','postal_code':'060-0033','phone':'011-208-7150'}
        self.entity={'id':'Q11226237','lastrevid':1,'labels':{'ja':{'value':'JR札幌病院'}},'claims':{'P13179':[{'mainsnak':{'datavalue':{'value':'0110114386'}}}]}}
    def test_confirmed_code_and_name(self):
        self.assertEqual(assess(self.row,[self.entity])['status'],'confirmed')
    def test_name_only_never_links(self):
        self.entity['claims']={}
        self.assertIsNone(assess(self.row,[self.entity])['qid'])
    def test_code_with_wrong_name_never_links(self):
        self.row['name']='別病院'
        self.assertIsNone(assess(self.row,[self.entity])['qid'])
    def test_duplicate_code_requires_review(self):
        second=copy.deepcopy(self.entity);second['id']='Q2'
        self.assertIsNone(assess(self.row,[self.entity,second])['qid'])
    def test_conflicting_phone_requires_review(self):
        self.entity['claims']['P1329']=[{'mainsnak':{'datavalue':{'value':'+819012345678'}}}]
        self.assertIsNone(assess(self.row,[self.entity])['qid'])
    def test_unsearched_is_not_absent(self):
        self.assertEqual(assess(self.row,[])['status'],'not_checked')
