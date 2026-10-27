"""Run the real local WB QueueWorker until N accepted designs; export offline review."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse,unquote
from printflow.config import read_env
from printflow.domain.models import JobStatus,JobKind
from printflow.repositories.jobs import JobRepository
from printflow.wb_studio.infrastructure.generation import Generator
from printflow.wb_studio.infrastructure.local import generate,LocalStorage
from printflow.scripts.wb_review_batch import read,write,report
from printflow.wb_studio.infrastructure.wb.search import parsing_batch


@parsing_batch
async def main(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    env={**read_env(),'PRINTFLOW_WB_KEEP_TEMPORARY':'1'};logfile=out/'requests.json';calls=read(logfile) if logfile.exists() else []
    def log(kind,state,**details):
        calls.append({'kind':kind,'state':state,'time':time.time(),**details});write(logfile,calls)
    class Metered(Generator):
        async def analyze_gallery(self,*a):
            log('analyze','start');return await super().analyze_gallery(*a)
        async def verify_prints(self,*a):
            log('verify_prints','start');r=await super().verify_prints(*a)
            log('verify_prints','result',verdicts=r);return r
        async def edit(self,files,prompt):
            log('image','start',inputs=[f[0] for f in files])
            return await super().edit(files,prompt)
    import printflow.wb_studio.application.studio as service
    import printflow.wb_studio.infrastructure.wb.search as search
    service.Generator=Metered
    if (out/'jobs.db').exists():
        existing=JobRepository(out/'jobs.db',timeout_sec=30)
        unfinished=[j for j in existing.list(product='tee_wb',limit=2000) if j.status in (JobStatus.PENDING,JobStatus.RUNNING)]
        if unfinished:
            prior=sorted(out.glob('sources-*.json'))
            if prior:
                print('RESUMING MASS QUEUE',len(unfinished),flush=True)
                await generate({'theme':args.theme,'sources':read(prior[-1]),'algorithm':'source_redraw','colors':['white','black']},out,env)
    candidates=[];archived={};cached={}
    captures=[] if args.fresh else [*Path('outputs').glob('wb-redraw-v9-*/state.json'),*Path('outputs').glob('wb-mass-v*-*/state.json')]
    if args.sources_from:
        # Replay another run's sources in its order, with its saved galleries.
        previous=Path(args.sources_from);captures=[previous/'state.json']
        replay=[s for path in sorted(previous.glob('sources-*.json')) for s in read(path)]
    for path in sorted(captures):
        for e in read(path):
            s=e['source'];candidates.append(s)
            if s.get('gallery_complete') and s.get('images'):archived[s['sku']]=s
            for index,local in e.get('result',{}).get('source_photos',{}).items():
                if int(index)>=len(s.get('images',[])):continue
                parsed=urlparse(local)
                if parsed.scheme!='file':continue
                name=unquote(parsed.path).lstrip('/')
                if Path(name).is_file():cached[s['images'][int(index)]]=Path(name)
    from printflow.wb_studio.application.studio import Studio
    downloader=Studio(SimpleNamespace(list=lambda **kw:[]),LocalStorage(out/'files'),env)
    async def fetch(url):
        return cached[url].read_bytes() if url in cached else await downloader.fetch_photo(url)
    if args.sources_from:
        candidates=replay
    elif not args.fresh:
        repo0=JobRepository(Path('outputs/wb-redraw-v9-live-20261025/jobs.db'),timeout_sec=30)
        for j in repo0.list(product='tee_wb',limit=100):candidates.extend(j.result.get('sources',[]))
        for path in sorted(Path('outputs').glob('wb-redraw-v9-*/search-*.json')):candidates.extend(read(path))
    attempted_file=out/'attempted.json';attempted=set(read(attempted_file)) if attempted_file.exists() else set()
    search_limit=0
    def entries():
        if not (out/'jobs.db').exists():return []
        repo=JobRepository(out/'jobs.db',timeout_sec=30)
        return [{'id':j.id,'source':j.payload['source'],'result':j.result,
                 'status':j.status.value,'error':j.error}
                for j in reversed(repo.list(product='tee_wb',limit=2000)) if j.kind==JobKind.WB_CARD]
    exhausted=False;ready=[]
    async def take(n):
        """Pick up to n new products, then open all their pages in one browser pass before generation."""
        nonlocal candidates,search_limit,exhausted
        picked=[]
        while len(ready)+len(picked)<n and not exhausted:
            if not candidates:
                if args.sources_from or search_limit>=args.max_search:exhausted=True;break
                search_limit+=args.search_step
                try:
                    found=await search.discover(args.theme,search_limit)
                    write(out/f'search-{int(time.time())}.json',{'query':args.theme,'limit':search_limit,'sources':found})
                except Exception as exc:
                    print('SEARCH FAILED',str(exc),flush=True);continue
                candidates=[c for c in found if c['sku'] not in attempted]
                print('SEARCH',args.theme,'limit',search_limit,'new',len(candidates),flush=True)
                if not candidates:exhausted=True;break
            source=candidates.pop(0);sku=source['sku']
            if sku in attempted:continue
            attempted.add(sku);picked.append(archived.get(sku,source))
        write(attempted_file,sorted(attempted))
        missing=[s['url'] for s in picked if not s.get('gallery_complete')]
        if missing:
            print('PARSING BATCH',len(missing),flush=True)
            resolved={}
            for start in range(0,len(missing),20):  # the resolver accepts at most 20 links per call
                resolved.update({s['sku']:s for s in await search.resolve_product_urls(missing[start:start+20],skip_errors=True)})
            print('PARSED',len(resolved),'of',len(missing),flush=True)
        else:resolved={}
        for source in picked:
            if source.get('gallery_complete'):ready.append(source)
            elif source['sku'] in resolved:ready.append(resolved[source['sku']])
            else:log('parse','failed',sku=source['sku'])
    while True:
        current=entries();done=sum(e['status']=='done' for e in current)
        if done>=args.count:break
        # Exactly the missing number; the next portion starts only after this one has finished.
        size=max(1,round((args.count-done)*args.overshoot))
        await take(size)
        batch=ready[:size];del ready[:size]
        if not batch:break
        print('MASS QUEUE',len(batch),'sources; already accepted',done,'target',args.count,flush=True)
        write(out/f'sources-{int(time.time())}.json',batch)
        # Only browser parsing overlaps with generation; parsed spares wait for the next portion.
        running=asyncio.create_task(generate({'theme':args.theme,'sources':batch,'algorithm':'source_redraw',
                                              'colors':['white','black']},out,env,fetch=fetch))
        await asyncio.gather(running,take(size))
        current=entries();write(out/'state.json',current)
        print('ACCEPTED',sum(e['status']=='done' for e in current),'TARGET',args.count,flush=True)
    current=entries();write(out/'state.json',current);report(out,current)
    done=sum(e['status']=='done' for e in current)
    print('FINAL',done,'designs',done*8,'generated photos; HTML',out/'review-portable.html',flush=True)
    if done<args.count:raise RuntimeError(f'Only {done}/{args.count} sources passed automatic checks; all failures preserved')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--count',type=int,default=20)
    p.add_argument('--theme',required=True)
    p.add_argument('--out',default='outputs/wb-mass-v12-cats20-20261025')
    p.add_argument('--overshoot',type=float,default=1,help='queue this many sources per missing design')
    p.add_argument('--search-step',type=int,default=30,help='how many more WB results each additional search requests')
    p.add_argument('--max-search',type=int,default=60,help='stop searching the theme beyond this many results')
    p.add_argument('--sources-from',help='replay sources and galleries of a previous run folder, no search')
    p.add_argument('--fresh',action='store_true',help='fresh search and galleries; do not import previous trial captures')
    asyncio.run(main(p.parse_args()))
