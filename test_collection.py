import unittest
from collect_materials import parse_mdb, summarize

class ParserTests(unittest.TestCase):
    def test_trailing_space_headers_and_equals_in_value(self):
        _, sections, _ = parse_mdb(b'[Header]\nDate=x\n[Steel A] \nType=Fixed_Solid\nNotes=a=b\n[Steel B]\t\nDensity=7\n')
        self.assertEqual([s['name'] for s in sections], ['Header', 'Steel A', 'Steel B'])
        self.assertEqual(sections[1]['entries'][1]['value'], 'a=b')

    def test_duplicate_values_are_preserved_and_flagged(self):
        _, sections, _ = parse_mdb(b'[A]\nBValue[0]=1\nBValue[0]=2\nHValue[0]=3\n')
        _, arrays, _, warnings = summarize(sections[0])
        self.assertEqual(len(arrays['BValue']), 2)
        self.assertIn('duplicate_key:BValue[0]', warnings)

    def test_missing_curve_axis_is_flagged(self):
        _, sections, _ = parse_mdb(b'[A]\nTemperature[0]=20\nBValue_Magnet[0]=1\n')
        _, _, curves, warnings = summarize(sections[0])
        self.assertFalse(curves[0]['indices_match'])
        self.assertIn('mismatched_curve_indices:magnet_bh', warnings)

    def test_comments_and_blank_values_retained(self):
        _, sections, _ = parse_mdb(b'[A]\nNotes=\n; comment\n')
        self.assertEqual(sections[0]['entries'][0]['value'], '')
        self.assertEqual(sections[0]['other_lines'][0]['text'], '; comment')

if __name__ == '__main__':
    unittest.main()
