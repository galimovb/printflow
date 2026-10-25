"""Batch template generation contract: staging, safe replacement and offline check mode."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from support import TempDir
from printflow.products.thermo.scripts import generate_blanks as module


def raw_asset(path, good=True):
    im=Image.new('RGB',(600,800),(220,237,252))
    ImageDraw.Draw(im).ellipse((400,-100,750,300),fill=(235,245,255))
    if good and path.stem != 'background':
        ImageDraw.Draw(im).rectangle((156,392,444,664),fill='white' if path.stem=='shirt' else 'ivory')
        ImageDraw.Draw(im).arc((220,224,380,460),180,360,fill='white' if path.stem=='shirt' else 'ivory',width=18)
    if not good:
        im=Image.new('RGB',(600,800),'white')
    im.save(path)


class ThermoTemplateTest(unittest.TestCase):
    def test_dry_run_writes_four_requests_and_never_calls_api(self):
        with TempDir() as tmp, patch.object(module,'read_env',return_value={}), patch.object(module.subprocess,'run') as run:
            self.assertEqual(module.main(['--dry-run','--out-dir',str(tmp)]),0)
            data=json.loads((tmp/'generation-plan.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['jobs']),4)
            self.assertEqual(data['cards'],6)
            self.assertTrue(all('full-frame vertical' in j['prompt'] for j in data['jobs']))
            run.assert_not_called()

    def test_all_assets_generated_in_one_cli_call_then_six_layouts(self):
        with TempDir() as tmp:
            cli=tmp/'cli.py';cli.write_text('# test',encoding='utf-8')
            def fake_run(command,**kwargs):
                raw=Path(command[command.index('--out-dir')+1])
                for name in module.SUBJECTS:raw_asset(raw/f'{name}.png')
            with patch.object(module,'read_env',return_value={'OPENAI_API_KEY':'test-key'}), patch.object(module.subprocess,'run',side_effect=fake_run) as run:
                self.assertEqual(module.main(['--out-dir',str(tmp),'--imagegen-cli',str(cli)]),0)
                self.assertEqual(run.call_count,1)
                self.assertEqual(len(list((tmp/'cards').glob('*.png'))),6)
                self.assertTrue((tmp/'blank-preview.jpg').is_file())
                for name in module.SUBJECTS:
                    with Image.open(tmp/f'{name}-scene.png') as im:
                        self.assertEqual(im.mode,'RGB')
                        self.assertEqual(im.size,(1200,1600))
            with patch.object(module,'read_env',return_value={}),patch.object(module.subprocess,'run') as run:
                self.assertEqual(module.main(['--check-only','--out-dir',str(tmp)]),0)
                run.assert_not_called()

    def test_failed_second_asset_does_not_replace_first(self):
        with TempDir() as tmp:
            cli=tmp/'cli.py';cli.write_text('# test',encoding='utf-8')
            old=tmp/'shirt-scene.png';old.write_bytes(b'approved-shirt')
            def fake_run(command,**kwargs):
                raw=Path(command[command.index('--out-dir')+1])
                raw_asset(raw/'background.png')
                raw_asset(raw/'accents.png')
                raw_asset(raw/'shirt.png')
                raw_asset(raw/'shopper.png',good=False)
            with patch.object(module,'read_env',return_value={'OPENAI_API_KEY':'test-key'}),patch.object(module.subprocess,'run',side_effect=fake_run):
                with self.assertRaises(ValueError):
                    module.main(['--out-dir',str(tmp),'--imagegen-cli',str(cli)])
            self.assertEqual(old.read_bytes(),b'approved-shirt')
            self.assertFalse((tmp/'shopper-scene.png').exists())

    def test_headline_overlap_is_rejected(self):
        with TempDir() as tmp:
            path=tmp/'shirt.png'
            raw_asset(path)
            with Image.open(path) as image:
                image=image.copy()
            ImageDraw.Draw(image).rectangle((150,120,450,500),fill='white')
            with self.assertRaisesRegex(ValueError,'headline'):
                module.validate_asset(image,'shirt')

    def test_standalone_import_does_not_load_other_products(self):
        import subprocess,sys
        code="import sys; import printflow.products.thermo.scripts.generate_blanks; assert not any(m.startswith(('printflow.products.shopper', 'printflow.products.mousepad')) for m in sys.modules)"
        subprocess.run([sys.executable,'-c',code],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
