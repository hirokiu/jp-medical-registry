import unittest
from jp_medical_registry.core import insurance_id, diff
class CoreTest(unittest.TestCase):
    def test_known_codes(self):
        self.assertEqual(insurance_id("13","医科","02,7075,1"),"1310270751")
        self.assertEqual(insurance_id("01","医科","01,1438,6"),"0110114386")
        self.assertEqual(insurance_id("13","薬局","0000001"),"1340000001")
    def test_ambiguity_rejected(self):
        for args in [("1","医科","0114386"),("48","医科","0114386"),("13","5","0114386"),("13","医科","0114386 (0134075)"),("13","医科","114386")]:
            with self.assertRaises(ValueError): insurance_id(*args)
    def test_missing_is_not_closure(self):
        self.assertEqual(diff({"dataset":"x","entities":[{"key":"a"}]},{"dataset":"x","entities":[]})["missing"],["a"])
