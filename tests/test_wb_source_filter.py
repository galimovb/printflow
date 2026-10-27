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
    def test_main_article_shape_with_reserved_studio_segment(self):
        from printflow.wb_studio.domain.models import vendor_codes
        self.assertEqual(vendor_codes(123, ["white", "black"]), {"white": "TEE-000000123-100W", "black": "TEE-000000123-100B"})


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


class PrintWithoutPoseTest(unittest.TestCase):
    def test_print_from_any_photo_when_no_adult_front_photo(self):
        d = SourceFilterTest.data(None)
        for photo in d["photos"]:
            photo["adult"] = False  # children wearing the shirt
        d["photos"][3]["role"] = "infographic"
        d["print_source"] = 2
        result = assess(d, 4)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["print_source"], 2)
        self.assertEqual(result["original_selected"], [])  # all frames use the fixed scenes

    def test_rejects_only_when_the_print_is_never_visible(self):
        d = SourceFilterTest.data(None)
        for photo in d["photos"]:
            photo["role"] = "infographic"
        self.assertFalse(assess(d, 4)["accepted"])
