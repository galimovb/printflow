"""Thermo pipeline integration: changing prints, isolated rendering, resumable upload and API."""
import asyncio
import copy
import io
import unittest
from dataclasses import replace
from PIL import Image
from fastapi.testclient import TestClient
from support import TempDir, test_container, png
from support_mousepad import FakeStorage, FakeFetcher, FakePublisher, FakeGenerator
from printflow.products import get_product
from printflow.products.thermo.product import Thermo
from printflow.domain.models import CardSpec, Job, JobStatus
from printflow.domain.errors import PermanentError
from printflow.services.cards.service import CardService
from printflow.api.app import create_app


class ThermoTest(unittest.TestCase):
    def test_bag_body_is_34_by_38_and_print_has_one_physical_scale(self):
        import numpy as np
        from printflow.products.thermo.infrastructure.gallery.renderer import garment_mockup
        product=Thermo()
        spec=product.config['gallery']['mockups']['shopper']
        rendered=garment_mockup(Image.new('RGBA',(210,346),'red'),[21,34.6],spec,product.templates_dir)
        pixels=np.asarray(rendered)
        alpha=pixels[:,:,3]>128
        widths=alpha.sum(axis=1)
        rows=np.flatnonzero(widths>=widths.max()*.9)
        columns=np.flatnonzero(alpha[(int(rows[0])+int(rows[-1]))//2])
        width=int(columns[-1]-columns[0]+1)
        height=int(rows[-1]-rows[0]+1)
        self.assertAlmostEqual(width/height,34/38,delta=.01)
        rgb=pixels[:,:,:3].astype(float)
        red=(rgb[:,:,0]>rgb[:,:,1]+50)&(rgb[:,:,0]>rgb[:,:,2]+50)&alpha
        ys,xs=np.where(red)
        self.assertAlmostEqual((xs.max()-xs.min()+1)/width,21/34,delta=.01)
        self.assertAlmostEqual((ys.max()-ys.min()+1)/(xs.max()-xs.min()+1),34.6/21,delta=.02)

    def test_actual_print_width_drives_height_listing_and_order_snapshot(self):
        from printflow.products.thermo.domain.assortment import sizes, caption
        from printflow.services.jobs.service import JobService
        from support import new_repository
        product=Thermo()
        product._config=copy.deepcopy(product.config)
        product._config['assortment']={'mode':'single'}
        image=Image.new('RGBA',(1000,1500))
        from PIL import ImageDraw
        ImageDraw.Draw(image).rectangle((100,100,899,1299),fill='red')
        data=io.BytesIO();image.save(data,format='PNG')
        config=product.resolve_print(data.getvalue())
        self.assertEqual(sizes(config)[0]['size_cm'],[21,31.5])
        self.assertEqual(caption(sizes(config)[0]),'21 × 31,5 см')
        self.assertIn('21 × 31,5 см',config['ozon']['name_template'])
        self.assertIn('21 × 31,5 см',config['ozon']['description_template'])
        with TempDir() as tmp:
            repo=new_repository(tmp)
            queue=JobService(repo,product='thermo',prepare_spec=Thermo().prepare_spec)
            card,_=queue.enqueue_card(CardSpec(theme='лиса'))
            repo.save_progress(card.id,stage='dimensions_done',result={'article':'TRM-000001','product_config':config})
            hires,_=queue.enqueue_hires('TRM-000001')
            self.assertEqual(sizes(hires.payload['product_config'])[0]['size_cm'],[21,31.5])

    def test_queue_freezes_single_a4_and_preserves_normal_merge_groups(self):
        from support import new_repository
        from printflow.services.jobs.service import JobService
        from printflow.domain.models import design_article, design_merge_group
        from printflow.products.thermo.domain.assortment import sizes
        with TempDir() as tmp:
            product=Thermo()
            product._config=copy.deepcopy(product.config)
            repo=new_repository(tmp)
            queue=JobService(repo,product='thermo',merge_designs=50,prepare_spec=product.prepare_spec)
            first,_=queue.enqueue_card(CardSpec(theme='лиса'),external_id='ref:fox')
            second,_=queue.enqueue_card(CardSpec(theme='цветы'),external_id='ref:flowers')
            self.assertEqual(first.group_id,second.group_id)
            self.assertNotEqual(first.design_number,second.design_number)
            group=design_merge_group('TRM-',first,50)
            self.assertEqual(group.key,f'TRM-{first.group_id:06d}')
            self.assertEqual(sizes(first.payload['product_config'])[0]['size_cm'],[21,29.7])
            product.config['single_size_cm']=[10,15]
            bound=product.for_spec(CardSpec.from_payload(first.payload))
            self.assertEqual(sizes(bound.config)[0]['size_cm'],[21,29.7])
            article=design_article('TRM-',first)
            repo.save_progress(first.id,stage='print_done',result={'article':article})
            hires,created=queue.enqueue_hires(article)
            self.assertTrue(created)
            self.assertEqual(hires.payload['product_config'],first.payload['product_config'])
            self.assertFalse(queue.enqueue_card(CardSpec(theme='лиса'),external_id='ref:fox')[1])

    def test_order_exports_proportional_height_at_300dpi_and_reuses_master(self):
        from printflow.services.hires.service import HiresService
        product=Thermo()
        art=Image.new('RGBA',(100,150),'red')
        buffer=io.BytesIO();art.save(buffer,format='PNG')
        master=buffer.getvalue()
        config=product.resolve_print(master)
        storage=FakeStorage()
        storage.objects['trm-high-resolution-prints/TRM-000001.png']=master
        class NoGeneration:
            async def hires_print(self, data):
                raise AssertionError('existing master must be reused')
        service=HiresService(config,storage,NoGeneration())
        job=Job(id='hires',number=0,status=JobStatus.RUNNING,product='thermo',
                payload={'kind':'hires','article':'TRM-000001','product_config':config})
        result=asyncio.run(service.run(job,lambda *_:None))
        self.assertEqual(len(result['print_files']),1)
        self.assertEqual(result['print_files'][0]['pixels'],[2480,3720])
        data=storage.objects['trm-high-resolution-prints/TRM-000001/300dpi/single.png']
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size,(2480,3720))
            self.assertAlmostEqual(image.info['dpi'][0],300,places=1)

    def test_single_default_is_portrait_a4_and_matches_both_garment_scales(self):
        from printflow.products.thermo.domain.assortment import configure, sizes
        from printflow.products.thermo.infrastructure.gallery.renderer import physical_print_zone
        config=configure(Thermo().config,'single')
        dimensions=sizes(config)[0]['size_cm']
        self.assertEqual(dimensions,[21,29.7])
        for mockup in config['gallery']['mockups'].values():
            zone=physical_print_zone((1200,1600),dimensions,mockup)
            width=zone[1][0]-zone[0][0]
            height=zone[2][1]-zone[1][1]
            self.assertAlmostEqual(width/(1200*mockup['reference_width_fraction']),21/mockup['reference_width_cm'])
            self.assertAlmostEqual(height/width,29.7/21)

    def test_assortment_validates_counts_and_builds_consistent_listing(self):
        from printflow.products.thermo.domain.assortment import configure, sizes, listing_config
        source=Thermo().config
        original=copy.deepcopy(source)
        for mode,dims in [('single',[[13,19]]),('set',[[6,9],[13,19]]),
                          ('set',[[4,6],[6,9],[8,12],[10,15],[12,18],[14,21]])]:
            config=listing_config(configure(source,mode,dims))
            self.assertEqual(len(sizes(config)),len(dims))
            self.assertEqual(config['ozon']['wishes']['Количество в упаковке'],str(len(dims)))
            for item in sizes(config):
                from printflow.products.thermo.domain.assortment import caption
                self.assertIn(caption(item),config['ozon']['description_template'])
            if mode=='single':
                self.assertNotIn('набор',config['ozon']['name_template'])
                self.assertIn('1 шт.',config['ozon']['name_template'])
        self.assertEqual(source,original)
        for mode,dims in [('single',[[6,9],[13,19]]),('set',[[13,19]]),
                          ('set',[[13,19],[6,9]]),('single',[[0,19]]),('single',[[float('nan'),19]])]:
            with self.assertRaises(ValueError):
                configure(source,mode,dims)

    def test_single_and_six_size_layouts_render_six_cards_without_set_copy_in_single(self):
        from printflow.products.thermo.domain.assortment import configure
        from printflow.products.thermo.infrastructure.gallery.renderer import compose, copy_for, set_sizes
        product=Thermo()
        art=Image.new('RGBA',(65,95),(240,15,20,255))
        for mode,dims in [('single',[[13,19]]),('set',[[4,6],[6,9],[8,12],[10,15],[12,18],[14,21]])]:
            config=configure(product.config,mode,dims)
            cards=compose(art,config,product.templates_dir)
            self.assertEqual(list(cards),product.gallery().slides)
            self.assertTrue(all(image.size==(1200,1600) for image in cards.values()))
            if mode=='single':
                self.assertIn('1 ШТ.',copy_for(set_sizes(config))['badge'])

    def test_flatlay_uses_centimetres_and_doubles_both_print_axes(self):
        from printflow.products.thermo.infrastructure.gallery.renderer import surface_print_zone
        spec={'surface_cm':[52,60],
              'surface':[[.2,.3],[.7,.3],[.7,.8],[.2,.8]]}
        small=surface_print_zone((1200,1600),(6.5,9.5),spec)
        large=surface_print_zone((1200,1600),(13,19),spec)
        self.assertAlmostEqual(small[1][0]-small[0][0],600*6.5/52)
        self.assertAlmostEqual(small[2][1]-small[1][1],800*9.5/60)
        self.assertAlmostEqual(large[1][0]-large[0][0],2*(small[1][0]-small[0][0]))
        self.assertAlmostEqual(large[2][1]-large[1][1],2*(small[2][1]-small[1][1]))
        with self.assertRaises(ValueError):
            surface_print_zone((1200,1600),(60,70),spec)

    def test_set_dimensions_change_only_the_selected_mockup(self):
        from PIL import ImageChops
        from printflow.products.thermo.infrastructure.gallery.renderer import compose
        product=Thermo()
        config=copy.deepcopy(product.config)
        config['assortment']={'mode':'set'}
        art=Image.new('RGBA',(65,95),(240,15,20,255))
        before=compose(art,config,product.templates_dir)
        config['set_sizes'][0]['size_cm']=[5,7.3]
        after=compose(art,config,product.templates_dir)
        for slide in ('02-shirt','03-shopper'):
            diff=ImageChops.difference(before[slide],after[slide]).getbbox()
            self.assertIsNotNone(diff)
            self.assertLessEqual(diff[2],400,slide)
            self.assertLessEqual(diff[3],1330,slide)
        self.assertEqual(before['05-application'].tobytes(),after['05-application'].tobytes())
        config['set_sizes']=config['set_sizes'][:2]
        self.assertEqual(len(compose(art,config,product.templates_dir)),6)

    def test_mockup_scale_is_physical_and_preserves_aspect(self):
        from printflow.products.thermo.infrastructure.gallery.renderer import physical_print_zone
        settings=Thermo().config['gallery']['mockups']
        for spec in settings.values():
            small=physical_print_zone((1254,1254),(6.5,9.5),spec)
            large=physical_print_zone((1254,1254),(13,19),spec)
            sw=small[1][0]-small[0][0]
            sh=small[2][1]-small[1][1]
            self.assertAlmostEqual(sw/sh,6.5/9.5)
            self.assertAlmostEqual(large[1][0]-large[0][0],sw*2)
            self.assertAlmostEqual(large[2][1]-large[1][1],sh*2)
            self.assertAlmostEqual(sw/(1254*spec['reference_width_fraction']),6.5/spec['reference_width_cm'])
        shirt=Image.open(Thermo().templates_dir/settings['shirt']['template'])
        self.assertEqual(shirt.mode,'RGBA')
        self.assertEqual(shirt.getchannel('A').getextrema(),(0,255))

    def test_generator_is_constructible_and_keeps_chromakey_transparent(self):
        from printflow.config import load_product_settings
        from printflow.products.thermo.infrastructure.print_generator import ThermoPrintGenerator
        settings = load_product_settings('MOUSEPAD').openai
        generator = ThermoPrintGenerator(replace(settings, api_key='test-key'), Thermo().config['generation'])
        self.assertIn('термонаклейке', generator.name_prompt)
        self.assertIn('heat-transfer', generator.preview_prompt('лиса'))
        self.assertIn('ONLY the printed design', generator.reference_prompt(''))
        im = Image.new('RGB', (100, 100), '#90EE90')
        from PIL import ImageDraw
        ImageDraw.Draw(im).ellipse((20, 20, 80, 80), fill='red')
        buf = io.BytesIO(); im.save(buf, format='PNG')
        out = Image.open(io.BytesIO(generator.finalize(buf.getvalue())))
        self.assertEqual(out.mode, 'RGBA')
        self.assertEqual(out.getchannel('A').getextrema(), (0, 255))

    def test_registry_and_actual_gallery_use_current_print_on_both_products(self):
        product = get_product('thermo')
        self.assertEqual(product.variants(CardSpec()), ['main'])
        from printflow.products.mousepad.infrastructure.gallery import slides as mouse
        before = (mouse.INK, mouse.TERRA, mouse.CREAM)
        template = Image.open(product.templates_dir/'shopper-transparent.png')
        self.assertEqual(template.mode, 'RGBA')
        self.assertEqual(template.getchannel('A').getextrema(), (0, 255))
        renderer = product.gallery()
        red = renderer.compose_print(png((240, 15, 20, 255)), 'main')
        blue = renderer.compose_print(png((15, 20, 240, 255)), 'main')
        self.assertEqual(len(red), 6)
        self.assertEqual((mouse.INK, mouse.TERRA, mouse.CREAM), before)
        for name in ('01-cover', '02-shirt', '03-shopper', '04-size'):
            self.assertNotEqual(red[name].tobytes(), blue[name].tobytes(), name)
        self.assertEqual(red['05-application'].tobytes(), blue['05-application'].tobytes())
        slides = renderer.render(png(), 'main')
        self.assertTrue(slides[0][0].endswith('_01-cover'))
        self.assertEqual(Image.open(io.BytesIO(slides[0][1])).size, (1200, 1600))

    def test_service_dry_run_then_publish_and_resume(self):
        async def run():
            product = Thermo()
            product._config = copy.deepcopy(product.config)
            storage, generator, publisher = FakeStorage(), FakeGenerator(), FakePublisher()
            # Test the real gallery in the shared card service.
            service = CardService(product, storage, generator, product.gallery(), lambda: publisher, FakeFetcher())
            job = Job(id='thermo-test', number=1, product='thermo', status=JobStatus.RUNNING,
                      payload=CardSpec(theme='лиса', dry_run=True).to_payload())
            result = await service.run(job, lambda stage, result: None)
            self.assertEqual(result['product_config']['resolved_print']['size_cm'],[21,21*360/440])
            self.assertEqual(result['article'], 'TRM-000001')
            self.assertEqual(len(result['images']['main']), 6)
            self.assertFalse(publisher.items)
            self.assertTrue(all(key.startswith(('trm-print/', 'trm-mockups/')) for key in storage.objects))
            # Unconfigured real publication fails before spending on generation.
            job.payload['dry_run'] = False
            with self.assertRaises(PermanentError):
                await service.run(job, lambda stage, result: None)
            product.config['ozon'].update(category_id=123, type_id=456, price=299,
                package={'width_mm':100, 'height_mm':150, 'depth_mm':2, 'weight_g':10})
            product.config['colors']['main']['ozon_value'] = [{'value':'разноцветный'}]
            job.result = {k:v for k,v in result.items() if k != 'ozon'}
            generated = list(generator.calls)
            published = await service.run(job, lambda stage, result: None)
            self.assertEqual(generator.calls, generated)
            self.assertEqual(publisher.items[0]['offer_id'], 'TRM-000001')
            self.assertIn('Термонаклейка', publisher.items[0]['name'])
            self.assertEqual(len(publisher.items[0]['images']), 6)
            self.assertFalse('Коврик' in str(publisher.items))
            self.assertEqual(published['ozon']['offers'], ['TRM-000001'])
            self.assertEqual(published['merge_group'],'TRM-000001')
        asyncio.run(run())

    def test_api_enqueues_in_own_product_namespace(self):
        with TempDir() as tmp:
            app = test_container(tmp)
            settings = replace(app.product_settings['mousepad'],
                ozon=replace(app.product_settings['mousepad'].ozon, env_prefix='THERMO'))
            app.settings = replace(app.settings, products=('shopper', 'mousepad', 'thermo'))
            app.product_settings['thermo'] = settings
            client = TestClient(create_app(app))
            response = client.post('/api/v1/thermo/jobs', headers={'Authorization':'Bearer test-token'},
                                   json={'theme':'Лиса', 'dry_run':True})
            self.assertIn(response.status_code, (200, 201, 202), response.text)
            self.assertEqual(app.job_repository.count_by_status('thermo'), {'pending':1})
            self.assertEqual(app.job_repository.count_by_status('mousepad'), {})

if __name__ == '__main__':
    unittest.main()
