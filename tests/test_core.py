import unittest
from jp_medical_registry.core import insurance_id, validate_insurance_id, diff
class CoreTest(unittest.TestCase):
    def test_canonical_rejects_regional_or_numeric_values(self):
        for value in ["0114386", 1310270751, "4810270751", "1320270751", "１３１０２７０７５１"]:
            with self.assertRaises(ValueError): validate_insurance_id(value)
    def test_known_codes(self):
        self.assertEqual(insurance_id("13","医科","02,7075,1"),"1310270751")
        self.assertEqual(insurance_id("01","医科","01,1438,6"),"0110114386")
        self.assertEqual(insurance_id("13","薬局","0000001"),"1340000001")
    def test_ambiguity_rejected(self):
        for args in [("1","医科","0114386"),("48","医科","0114386"),("13","5","0114386"),("13","医科","0114386 (0134075)"),("13","医科","114386")]:
            with self.assertRaises(ValueError): insurance_id(*args)
    def test_ten_digit_input_preserves_leading_zero(self):
        self.assertEqual(insurance_id("01", "医科", "0110114386"), "0110114386")
        self.assertEqual(insurance_id("13", "医科", "１３１０２７０７５１"), "1310270751")
    def test_ten_digit_input_requires_matching_context(self):
        for prefecture, kind, code in [("13", "医科", "0110114386"),
                                       ("01", "薬局", "0110114386"),
                                       ("01", "医科", "01101143860"),
                                       ("01", "医科", "011011438")]:
            with self.assertRaises(ValueError): insurance_id(prefecture, kind, code)
    def test_missing_is_not_closure(self):
        self.assertEqual(diff({"dataset":"x","entities":[{"key":"a"}]},{"dataset":"x","entities":[]})["missing"],["a"])
