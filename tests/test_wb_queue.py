import asyncio,copy,json,sqlite3,unittest,zipfile
from unittest.mock import patch
from support import TempDir,new_repository
from support_mousepad import FakeStorage
from test_wb_studio import Images,image
from printflow.domain.models import JobKind,JobStatus
from printflow.domain.errors import PermanentError,RetryLater
from printflow.wb_studio.application.studio import Studio
from printflow.wb_studio.config import load_config
from printflow.wb_studio.infrastructure.wb.publisher import Publisher,build_group_payload

FAST={'PRINTFLOW_WB_MERGE_DESIGNS':'2','PRINTFLOW_WB_WORKERS':'2',
      'PRINTFLOW_WB_QUEUE_POLL_SEC':'.01','PRINTFLOW_WB_RETRY_DELAYS_SEC':'0,0,0'}

def draft(number):
    config=load_config();config.update(price=1200,sizes=[{'techSize':'S','wbSize':'46'},{'techSize':'L','wbSize':'50'}])
    return {'config':config,'text':{'title':f'Футболка {number}','description':f'Рисунок {number}'},
        'images':{c:[f'https://s3/{number}/{c}/{i}.jpg' for i in range(6)] for c in ('white','black')},
        'vendor_codes':{c:f'TEE-{number:09}-100'+('W' if c=='white' else 'B') for c in ('white','black')},'review_required':True}


class WbQueueTest(unittest.TestCase):
    def test_print_and_gallery_use_separate_buckets_and_routing_is_persistent(self):
        async def run():
            with TempDir() as tmp:
                storage=FakeStorage();repo=new_repository(tmp)
                async def fetch(_):return image()
                studio=Studio(repo,storage,{},generator=Images(),fetch=fetch)
                config=studio.configuration(['white']);config['photos_per_color']=2
                job,_=repo.create({'kind':'wb_card','theme':'test','source':{'image':'https://source'},'config':config},product='tee_wb',numbered=True)
                result=await studio.card(job,lambda *_:None)
                self.assertEqual(result['storage_buckets'],{'prints':'tee-prints','mockups':'tee-mockups','temporary':'tee-temporary-storage'})
                self.assertEqual([key for key in storage.objects if key.startswith('tee-prints/')],[f'tee-prints/printflow-wb/{job.id}/print.png',f'tee-prints/printflow-wb/{job.id}/prints/white.png',f'tee-prints/TEE-{job.design_number:09d}-100W.png'])
                self.assertTrue(result['images']['white'][0].startswith('https://s3/tee-mockups/'))
                self.assertFalse(any(key.startswith('tee-temporary-storage/') for key in storage.objects))
                self.assertTrue(result['temporary_removed'])
                changed=Studio(repo,storage,{'PRINTFLOW_WB_PRINTS_BUCKET':'different','PRINTFLOW_WB_MOCKUPS_BUCKET':'different'})
                self.assertEqual(changed.storage_buckets(result),{'prints':'tee-prints','mockups':'tee-mockups','temporary':'tee-temporary-storage'})
                self.assertEqual(studio.storage_buckets({'print':'https://old-print'}),{'prints':'tee-prints','mockups':'tee-prints','temporary':'tee-temporary-storage'})
        asyncio.run(run())

    def test_discovery_barrier_precedes_generation_even_during_retry_wait(self):
        with TempDir() as tmp:
            repo=new_repository(tmp)
            card,_=repo.create({'kind':'wb_card'},product='tee_wb')
            discovery,_=repo.create({'kind':'wb_discover','theme_key':'wb-search'},product='tee_wb')
            self.assertEqual(repo.claim_next('tee_wb').id,discovery.id)
            self.assertIsNone(repo.claim_next('tee_wb'))
            repo.requeue(discovery.id,error='temporary',delay_sec=60)
            self.assertIsNone(repo.claim_next('tee_wb'))
            repo.fail(discovery.id,'failed search')
            self.assertEqual(repo.claim_next('tee_wb').id,card.id)

    def test_standard_gallery_limits_requests_per_print_and_resumes_completed_photos(self):
        class Limited(Images):
            active=0;peak=0
            async def standard_photo(self,art,product,color,index,white_scene=None):
                Limited.active+=1;Limited.peak=max(Limited.peak,Limited.active)
                await asyncio.sleep(.02)
                Limited.active-=1
                return await super().standard_photo(art,product,color,index,white_scene)
        async def run():
            with TempDir() as tmp:
                repo=new_repository(tmp);generator=Limited()
                async def search(*_):return [{'sku':'1','image':'https://s3/ref.png'}]
                async def fetch(_):return image()
                studio=Studio(repo,FakeStorage(),{'PRINTFLOW_WB_REQUESTS_PER_PRINT':'2'},search=search,fetch=fetch,generator=generator)
                campaign,_=studio.campaign(['гонки'],10,design_limit=1)[0]
                job=repo.get((await studio.discovery(campaign,lambda *_:None))['cards'][0]['id'])
                def save(stage,result):repo.save_progress(job.id,stage=stage,result=result)
                result=await studio.card(job,save)
                self.assertLessEqual(Limited.peak,2)
                self.assertTrue(all(len(result['images'][c])==6 for c in ('white','black')))
                before=len(generator.calls)
                await studio.card(repo.get(job.id),save)
                self.assertEqual(len(generator.calls),before)
        asyncio.run(run())

    def test_mass_cli_enqueues_both_colours_without_calling_generator(self):
        import sys
        from printflow.scripts import wb_batch
        env={'PRINTFLOW_WB_API_TOKEN':'test','PRINTFLOW_WB_MERGE_DESIGNS':'2'}
        with patch.object(wb_batch,'read_env',return_value=env),patch.object(sys,'argv',
                ['wb_batch','--theme','гонки','--api','http://127.0.0.1:8090']),patch.object(wb_batch.httpx,'Client') as client:
            response=client.return_value.__enter__.return_value.post.return_value
            response.json.return_value={'jobs':[{'id':'queued','created':True}]}
            wb_batch.main()
            call=client.return_value.__enter__.return_value.post.call_args
            self.assertEqual(call.args[0],'/api/v1/wb-studio/campaigns')
            self.assertEqual(call.kwargs['json']['colors'],['white','black'])
            self.assertEqual(call.kwargs['json']['design_limit'],10)

    def test_default_colours_and_immutable_groups_with_partial_tail(self):
        async def run():
            with TempDir() as tmp:
                repo=new_repository(tmp)
                async def search(*_):return [{'sku':str(i),'image':'https://s3/ref.png'} for i in range(5)]
                studio=Studio(repo,FakeStorage(),FAST,search=search)
                campaign,_=studio.campaign(['гонки'],10,design_limit=5)[0]
                self.assertEqual(campaign.payload['config']['colors'],['white','black'])
                result=await studio.discovery(campaign,lambda *_:None)
                cards=[repo.get(x['id']) for x in result['cards']]
                self.assertEqual([j.payload['merge_group_size'] for j in cards],[2,2,2,2,1])
                self.assertEqual([j.payload['merge_position'] for j in cards],[1,2,1,2,1])
                self.assertEqual(len({j.payload['merge_group'] for j in cards}),3)
                self.assertEqual(len(repo.wb_group_cards(cards[0].payload['merge_group'])),2)
                studio.env={**FAST,'PRINTFLOW_WB_MERGE_DESIGNS':'3'}
                again=await studio.discovery(campaign,lambda *_:None)
                self.assertEqual([x['id'] for x in result['cards']],[x['id'] for x in again['cards']])
                other,_=studio.campaign(['другая тема'],10,design_limit=1)[0]
                new=await studio.discovery(other,lambda *_:None)
                self.assertNotEqual(new['cards'][0]['merge_group'],cards[0].payload['merge_group'])
        asyncio.run(run())

    def test_local_uses_claimed_queue_retries_and_exports_both_colours(self):
        from printflow.wb_studio.infrastructure.local import generate
        class Flaky(Images):
            failed=False
            async def standard_photo(self,art,product,color,index,white_scene=None):
                if color=='black' and index==2 and not self.failed:
                    Flaky.failed=True;raise RuntimeError('temporary image error')
                return await super().standard_photo(art,product,color,index,white_scene)
        async def run():
            with TempDir() as tmp:
                generator=Flaky()
                async def search(*_):return [{'sku':str(i),'image':'https://s3/ref.png'} for i in range(3)]
                async def fetch(_):return image()
                body={'themes':['гонки'],'limit':10,'design_limit':3}
                results=await generate(body,tmp,FAST,generator=generator,search=search,fetch=fetch)
                self.assertEqual(len(results),3)
                self.assertTrue(all(set(e['result']['images'])=={'white','black'} for e in results))
                self.assertTrue(all(len(v)==6 for e in results for v in e['result']['images'].values()))
                self.assertEqual(generator.calls.count('extract'),3)
                self.assertEqual(generator.calls.count('describe'),3)
                db=sqlite3.connect(tmp/'jobs.db')
                try:
                    attempts=[r[0] for r in db.execute("SELECT attempts FROM jobs WHERE json_extract(payload,'$.kind')='wb_card'")]
                finally:db.close()
                self.assertEqual(sorted(attempts),[1,1,2])
                groups=json.loads((tmp/'groups.json').read_text(encoding='utf-8'))
                self.assertEqual(sorted(g['designs'] for g in groups),[1,2])
                with zipfile.ZipFile(tmp/'ready-cards.zip') as z:
                    photos=[n for n in z.namelist() if n.endswith(tuple(f'/{i:02}.jpg' for i in range(1,7)))]
                    self.assertEqual(len(photos),36)
                calls=list(generator.calls)
                await generate(body,tmp,FAST,generator=generator,search=search,fetch=fetch)
                self.assertEqual(generator.calls,calls)
        asyncio.run(run())

    def test_group_publication_waits_for_all_members_and_deduplicates(self):
        async def run():
            with TempDir() as tmp:
                repo=new_repository(tmp)
                async def search(*_):return [{'sku':str(i),'image':'https://s3/ref.png'} for i in range(3)]
                studio=Studio(repo,FakeStorage(),FAST,search=search)
                campaign,_=studio.campaign(['гонки'],10)[0];result=await studio.discovery(campaign,lambda *_:None)
                cards=[repo.get(x['id']) for x in result['cards']]
                repo.complete(cards[0].id,draft(1))
                with self.assertRaisesRegex(ValueError,'все принты'):studio.enqueue_publication(cards[0].id)
                repo.complete(cards[1].id,draft(2));repo.complete(cards[2].id,draft(3))
                with patch('printflow.wb_studio.application.studio.load_config',return_value=draft(1)['config']):
                    one,created=studio.enqueue_publication(cards[0].id);two,again=studio.enqueue_publication(cards[1].id)
                    tail,_=studio.enqueue_publication(cards[2].id)
                self.assertTrue(created);self.assertFalse(again);self.assertEqual(one.id,two.id)
                self.assertEqual(len(one.payload['drafts']),2);self.assertEqual(len(tail.payload['drafts']),1)
                self.assertEqual(one.kind,JobKind.WB_PUBLISH)
        asyncio.run(run())

    def test_group_upload_and_reconciliation_never_recreate_cards(self):
        async def run():
            drafts=[draft(1),draft(2)];calls=[];cards={};state={}
            async def request(path,body):
                calls.append((path,copy.deepcopy(body)))
                if path.endswith('/list'):
                    vendor=body['settings']['filter']['textSearch'];return {'cards':[cards[vendor]] if vendor in cards else []}
                if path.endswith('/barcodes'):return {'data':[str(i) for i in range(body['count'])]}
                if path.endswith('/upload'):
                    for i,v in enumerate(body[0]['variants']):cards[v['vendorCode']]={'vendorCode':v['vendorCode'],'nmID':100+i,'imtID':10+i}
                if path.endswith('/moveNm'):
                    for c in cards.values():c['imtID']=body['targetIMT']
                return {'error':False}
            def save(value):state.clear();state.update(copy.deepcopy(value))
            publisher=Publisher('test',request)
            with patch('printflow.wb_studio.infrastructure.wb.publisher.asyncio.sleep',return_value=None):
                with self.assertRaises(RetryLater):await publisher.publish_group(drafts,{},save)
                result=await publisher.publish_group(drafts,state,save)
                count=len(calls);await publisher.publish_group(drafts,result,save);self.assertEqual(len(calls),count)
            self.assertTrue(result['complete']);self.assertTrue(result['merged'])
            self.assertEqual(sum(p.endswith('/upload') for p,_ in calls),1)
            payload=next(b for p,b in calls if p.endswith('/upload'))
            self.assertEqual(len(payload),1);self.assertEqual(len(payload[0]['variants']),4)
            self.assertTrue(all(size['price']==1200 for variant in payload[0]['variants'] for size in variant['sizes']))
            self.assertFalse(any(path.startswith('/api/v2/') for path,_ in calls))
            self.assertEqual(result['creation_price'],1200)
            self.assertEqual(len({s['skus'][0] for v in payload[0]['variants'] for s in v['sizes']}),8)
            for v in payload[0]['variants']:
                expected='белый' if v['vendorCode'].endswith('W') else 'черный'
                self.assertEqual(next(c['value'] for c in v['characteristics'] if c['id']==14177449),[expected])
            self.assertEqual(sum(p.endswith('/media/save') for p,_ in calls),4)
            self.assertFalse(any('/update' in p for p,_ in calls))
        asyncio.run(run())

    def test_group_limits_are_validated_before_requests(self):
        from printflow.wb_studio.config import merge_designs,default_colors as colors
        self.assertEqual(colors({}),['white','black'])
        with self.assertRaises(ValueError):merge_designs({'PRINTFLOW_WB_MERGE_DESIGNS':'16'})
        with self.assertRaises(PermanentError):build_group_payload([draft(i) for i in range(16)],[])
        with self.assertRaises(PermanentError):build_group_payload([draft(1),draft(1)],['x']*8)


class WbGenderTest(unittest.TestCase):
    def test_gender_follows_audience_and_unisex_stays_empty(self):
        from printflow.wb_studio.infrastructure.wb.publisher import build_payload
        def gender(audience):
            card=draft(1);card['analysis']={'audience':audience};card['config']['gender_attribute_id']=204557
            variant=build_payload(card,[f'b{i}' for i in range(4)])[0]['variants'][0]
            return [c['value'] for c in variant['characteristics'] if c['id']==card['config']['gender_attribute_id']]
        self.assertEqual(gender('female'),[['Женский']])
        self.assertEqual(gender('male'),[['Мужской']])
        self.assertEqual(gender('unisex'),[])

    def test_gender_is_not_sent_without_configured_attribute(self):
        from printflow.wb_studio.infrastructure.wb.publisher import build_payload
        card=draft(1);card['analysis']={'audience':'female'}
        names=[c['value'] for c in build_payload(card,[f'b{i}' for i in range(4)])[0]['variants'][0]['characteristics']]
        self.assertNotIn(['Женский'],names)


class AutoPublishTest(unittest.TestCase):
    def test_group_is_published_once_all_members_finished_without_failed_ones(self):
        from printflow.domain.models import JobStatus
        with TempDir() as tmp:
            repo=new_repository(tmp);studio=Studio(repo,FakeStorage(),FAST)
            members=[]
            for i in range(3):
                job,_=repo.create({'kind':'wb_card','merge_group':'PFWG-x-1','merge_group_size':3,'source':{'sku':str(i)},'config':{'auto_publish':True}},
                                  product='tee_wb',numbered=True)
                members.append(job)
            card=draft(1)
            repo.save_progress(members[0].id,stage='done',result=card);repo.complete(members[0].id,card)
            self.assertEqual(studio.publish_finished_groups(),[])  # others still pending
            repo.fail(members[1].id,'rejected by filter')
            card2=draft(2);repo.complete(members[2].id,card2)
            created=studio.publish_finished_groups()
            self.assertEqual(len(created),1)
            publication=created[0][0]
            self.assertEqual(publication.payload['card_ids'],[members[0].id,members[2].id])
            self.assertEqual(studio.publish_finished_groups(),[])  # never twice

    def test_cards_created_without_auto_publication_are_never_published(self):
        with TempDir() as tmp:
            repo=new_repository(tmp);studio=Studio(repo,FakeStorage(),FAST)
            job,_=repo.create({'kind':'wb_card','merge_group':'PFWG-old-1','merge_group_size':1,'source':{'sku':'1'},'config':{}},
                              product='tee_wb',numbered=True)
            repo.complete(job.id,draft(1))
            self.assertEqual(studio.publish_finished_groups(),[])
            self.assertFalse(Studio(repo,FakeStorage(),FAST).configuration()['auto_publish'])
            self.assertTrue(Studio(repo,FakeStorage(),{**FAST,'PRINTFLOW_WB_AUTO_PUBLISH':'1'}).configuration()['auto_publish'])


class ReserveTest(unittest.TestCase):
    def test_reserve_replaces_only_rejected_prints(self):
        with TempDir() as tmp:
            repo=new_repository(tmp);studio=Studio(repo,FakeStorage(),FAST)
            sources=[{'sku':str(i),'url':f'https://www.wildberries.ru/catalog/{i}/detail.aspx','image':'https://s3/1.png',
                      'images':['https://s3/1.png'],'gallery_complete':True} for i in range(5)]
            config=studio.configuration(algorithm='source_redraw')
            campaign,_=repo.create({'kind':'wb_discover','theme':'гонки','limit':5,'config':config,'design_limit':2},product='tee_wb')
            repo.complete(campaign.id,{'sources':sources})
            first=studio.enqueue_cards(repo.get(campaign.id),sources[:2])
            self.assertEqual(studio.top_up_campaigns(),[])  # nothing rejected yet
            repo.fail(first[0]['id'],'PermanentError: Исходная карточка отклонена фильтром')
            added=studio.top_up_campaigns()
            self.assertEqual([x['sku'] for x in added],['2'])
            self.assertEqual(added[0]['merge_group'],f'PFWG-{campaign.id}-2')
            self.assertEqual(studio.top_up_campaigns(),[])  # never twice
            repo.fail(first[1]['id'],'RuntimeError: HTTP 429 (credit_balance_exhausted)')
            self.assertEqual(studio.top_up_campaigns(),[])  # transient failure waits for a retry


    def test_finished_theme_is_regrouped_by_cards_with_colors_counted(self):
        with TempDir() as tmp:
            repo=new_repository(tmp)
            studio=Studio(repo,FakeStorage(),{**FAST,'PRINTFLOW_WB_AUTO_PUBLISH':'1','PRINTFLOW_WB_GROUP_CARDS':'4'})
            sources=[{'sku':str(i),'url':f'https://www.wildberries.ru/catalog/{i}/detail.aspx','image':'https://s3/1.png',
                      'images':['https://s3/1.png'],'gallery_complete':True} for i in range(5)]
            config=studio.configuration(algorithm='source_redraw')
            campaign,_=repo.create({'kind':'wb_discover','theme':'гонки','limit':5,'config':config,'design_limit':3},product='tee_wb')
            repo.complete(campaign.id,{'sources':sources})
            first=studio.enqueue_cards(repo.get(campaign.id),sources[:3])
            repo.complete(first[0]['id'],draft(1));repo.complete(first[1]['id'],draft(2))
            repo.fail(first[2]['id'],'PermanentError: Исходная карточка отклонена фильтром')
            with patch('printflow.wb_studio.application.studio.load_config',return_value=draft(1)['config']):
                self.assertEqual(studio.publish_finished_groups(),[])  # the reserve still refills the theme
                extra=studio.top_up_campaigns()
                self.assertEqual(studio.publish_finished_groups(),[])  # the refill is still generating
                repo.complete(extra[0]['id'],draft(3))
                created=studio.publish_finished_groups()
                self.assertEqual([len(job.payload['drafts']) for job,_ in created],[2,1])  # 4 cards = 2 prints x 2 colors
                first=repo.get(first[0]['id']).design_number
                self.assertEqual(created[0][0].payload['merge_group'],f'PFWG-{campaign.id}-t{first}')
                self.assertEqual(studio.publish_finished_groups(),[])  # never twice

    def test_prints_sent_by_an_older_group_are_not_sent_again(self):
        with TempDir() as tmp:
            repo=new_repository(tmp)
            studio=Studio(repo,FakeStorage(),{**FAST,'PRINTFLOW_WB_AUTO_PUBLISH':'1','PRINTFLOW_WB_GROUP_CARDS':'4'})
            sources=[{'sku':str(i),'url':f'https://www.wildberries.ru/catalog/{i}/detail.aspx','image':'https://s3/1.png',
                      'images':['https://s3/1.png'],'gallery_complete':True} for i in range(2)]
            config=studio.configuration(algorithm='source_redraw')
            campaign,_=repo.create({'kind':'wb_discover','theme':'гонки','limit':2,'config':config,'design_limit':2},product='tee_wb')
            repo.complete(campaign.id,{'sources':sources})
            first=studio.enqueue_cards(repo.get(campaign.id),sources)
            repo.complete(first[0]['id'],draft(1));repo.complete(first[1]['id'],draft(2))
            with patch('printflow.wb_studio.application.studio.load_config',return_value=draft(1)['config']):
                studio.create_publication(first[0]['id'],'PFWG-old-1',[repo.get(first[0]['id'])])
                created=studio.publish_finished_groups()
            self.assertEqual([job.payload['card_ids'] for job,_ in created],[[first[1]['id']]])


class FullHistoryTest(unittest.TestCase):
    def test_background_decisions_see_jobs_beyond_the_listing_cap(self):
        with TempDir() as tmp:
            repo=new_repository(tmp)
            items=[({'kind':'wb_card','theme':'t','source':{'sku':str(i)},'config':{}},f'x-{i}') for i in range(520)]
            repo.create_many(items,product='tee_wb',numbered=True)
            self.assertEqual(len(repo.list(product='tee_wb',limit=10000)),500)  # the API listing stays capped
            everything=repo.all('tee_wb')
            self.assertEqual(len(everything),520)
            self.assertEqual(everything[0].payload['source']['sku'],'0')  # oldest first


class ClaimOrderTest(unittest.TestCase):
    def test_publication_is_claimed_before_older_cards_and_during_a_search(self):
        with TempDir() as tmp:
            repo=new_repository(tmp)
            repo.create_many([({'kind':'wb_card','theme':'t','source':{'sku':str(i)},'config':{}},f'c-{i}') for i in range(3)],
                             product='tee_wb',numbered=True)
            repo.create({'kind':'wb_discover','theme':'next','limit':1,'config':{}},product='tee_wb',external_id='d')
            publication,_=repo.create({'kind':'wb_publish','card_ids':['x'],'merge_group':'g'},product='tee_wb',external_id='p')
            self.assertEqual(repo.claim_next('tee_wb').payload['kind'],'wb_discover')  # the search runs first
            self.assertEqual(repo.claim_next('tee_wb').id,publication.id)  # not blocked by it, ahead of cards


class BrowserFallbackTest(unittest.TestCase):
    def test_bundled_chromium_without_google_chrome(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from printflow.wb_studio.infrastructure.wb.search import open_session
        context=SimpleNamespace(set_default_timeout=lambda *_:None,set_default_navigation_timeout=lambda *_:None,
                                add_init_script=AsyncMock())
        launch=AsyncMock(return_value=context)
        playwright=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        with TempDir() as tmp, patch('pathlib.Path.is_file',return_value=False):
            asyncio.run(open_session(playwright,{'PRINTFLOW_WB_BROWSER_PROFILE':str(tmp)}))
        self.assertNotIn('executable_path',launch.await_args.kwargs)
