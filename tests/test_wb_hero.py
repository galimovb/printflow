import io,unittest
import numpy as np
from PIL import Image,ImageDraw
from printflow.wb_studio.infrastructure.rendering.hero import load_calibration,placement_geometry,prepare_hero

class HeroGeometryTest(unittest.TestCase):
    def test_shared_plane_is_orthogonal_centered_and_same_for_both_colours(self):
        c,_=load_calibration()
        for size in ((854,1043),(400,400),(200,1200),(1200,200)):
            g=placement_geometry(size,(1086,1448),c)
            q=np.array(g['corners_px']);u=q[1]-q[0];v=q[3]-q[0]
            self.assertAlmostEqual(float(u@v),0,places=7)
            self.assertAlmostEqual(np.linalg.norm(u)/np.linalg.norm(v),size[0]/size[1],places=10)
            self.assertAlmostEqual(np.degrees(np.arctan2(-u[1],u[0])),c['angle_degrees'],places=10)
            np.testing.assert_allclose((q[0]+q[1])/2,g['top_center_px'])
            np.testing.assert_allclose((q[2]+q[3])/2,g['bottom_center_px'])
            self.assertLessEqual(g['height_cm'],c['max_print_height_cm']+1e-9)
    def test_prepared_colours_share_exact_geometry_and_original_art_is_unchanged(self):
        artwork=Image.new('RGBA',(400,600),(0,0,0,0));d=ImageDraw.Draw(artwork)
        d.rectangle((0,0,399,599),outline='#CE9B48',width=10)
        d.line((200,0,200,599),fill='#FF0000',width=4)
        buf=io.BytesIO();artwork.save(buf,format='PNG');art=buf.getvalue()
        white,wg=prepare_hero(art,'white');black,bg=prepare_hero(art,'black')
        self.assertEqual(wg,bg)
        self.assertNotEqual(white,black)
        self.assertEqual(Image.open(io.BytesIO(white)).size,(1086,1448))
        self.assertEqual(buf.getvalue(),art)
