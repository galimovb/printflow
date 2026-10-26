import copy,unittest
from printflow.wb_studio.domain.source_filter import assess
class SourceFilterTest(unittest.TestCase):
 def data(self):return {'theme_match':True,'single_print':True,'print_count':1,'main_print_side':'front','print_width':.55,'reaches_edges':False,'print_source':0,'selected':[0,1,2,3],
  'photos':[{'index':i,'role':'front','same_print':True,'normal_light':True,'adult':True} for i in range(4)]}
 def test_accepts_four_matching_fronts(self):self.assertTrue(assess(self.data(),4)['accepted'])
 def test_rejects_wrong_or_unknown_theme(self):
  for value in (False,None):
   d=self.data();d['theme_match']=value;self.assertFalse(assess(d,4)['accepted'])
 def test_rejects_back_or_two_sided_print(self):
  for value in ('back','both','unknown'):
   d=self.data();d['main_print_side']=value;self.assertFalse(assess(d,4)['accepted'])
 def test_missing_views_are_planned_from_valid_front_only(self):
  d=self.data();d['photos'][2]['role']='back';d['photos'][3]['normal_light']=False
  r=assess(d,4);self.assertTrue(r['accepted']);self.assertEqual(r['selected'],[0,1,0,0]);self.assertEqual(r['generated_extra_frames'],[2,3]);self.assertEqual(len(r['rejected_photos']),2)
 def test_unique_available_sources_are_preferred(self):
  d=self.data();d['selected']=[0,1,0,1];r=assess(d,4);self.assertTrue(r['accepted']);self.assertEqual(r['selected'],[0,1,2,3]);self.assertEqual(r['generated_extra_frames'],[])
 def test_ineligible_print_source_falls_back_to_best_eligible(self):
  d=self.data();d['photos'][0]['adult']=False;d['print_source']=0;r=assess(d,4);self.assertTrue(r['accepted']);self.assertEqual(r['print_source'],1)
 def test_every_photo_must_be_classified(self):self.assertFalse(assess(self.data(),5)['accepted'])

 def test_rejects_two_separate_prints(self):
  d=self.data();d.update(single_print=False,print_count=2);self.assertFalse(assess(d,4)['accepted'])
 def test_rejects_unconfirmed_print_count(self):
  d=self.data();d.pop('single_print');self.assertFalse(assess(d,4)['accepted'])
 def test_one_eligible_source_generates_three_extra_views(self):
  d=self.data()
  for p in d['photos'][1:]:p['role']='back'
  r=assess(d,4);self.assertTrue(r['accepted']);self.assertEqual(r['selected'],[0,0,0,0]);self.assertEqual(r['generated_extra_frames'],[1,2,3])
 def test_rejects_full_width_or_unmeasured_print(self):
  for value in (.9,None,0,1.5):
   d=self.data();d['print_width']=value;self.assertFalse(assess(d,4)['accepted'])
  d=self.data();d['print_width']=.7;self.assertTrue(assess(d,4,.8)['accepted']);self.assertFalse(assess(d,4,.6)['accepted'])


class VendorCodeTest(unittest.TestCase):
    def test_design_group_color_and_disjoint_from_main_articles(self):
        from printflow.wb_studio.domain.models import group_number, vendor_codes
        codes = vendor_codes(123, ["white", "black"], group_number("PFWG-abc-7"))
        self.assertEqual(codes, {"white": "TEE-000123-007-W", "black": "TEE-000123-007-B"})
        self.assertEqual(group_number(None), 1)
        # Main ozon-tee articles carry 9 digits after TEE-, studio codes 6.
        self.assertNotRegex(codes["white"], r"^TEE-\d{9}")


class EdgeAndWidthTest(unittest.TestCase):
    def data(self):
        return SourceFilterTest.data(None)

    def test_limit_itself_rejects_and_edges_reject(self):
        d = self.data()
        d["print_width"] = 0.7
        self.assertFalse(assess(d, 4, 0.7)["accepted"])
        for value in (True, None):
            d = self.data()
            d["reaches_edges"] = value
            self.assertFalse(assess(d, 4)["accepted"])
