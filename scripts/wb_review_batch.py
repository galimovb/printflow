"""Local WB redraw batch and portable, embedded before/after HTML. Never publishes."""
import argparse
import asyncio
import base64
import copy
import html
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

from PIL import Image
from printflow.config import read_env
from printflow.domain.models import Job, JobStatus
from printflow.repositories.jobs import JobRepository
from printflow.wb_studio.infrastructure.local import LocalStorage
from printflow.wb_studio.application.studio import Studio
from printflow.wb_studio.infrastructure.wb.browser import parsing_batch


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path=Path(path)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def image_uri(url, width=1000):
    parsed=urlparse(url)
    if parsed.scheme!='file':raise ValueError('Review accepts only local files')
    name=unquote(parsed.path)
    if len(name)>2 and name[0]=='/' and name[2]==':':name=name[1:]
    with Image.open(name) as im:
        im=im.convert('RGB');im.thumbnail((width,1600))
        buffer=io.BytesIO();im.save(buffer,format='JPEG',quality=88)
    return 'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()


def report(out, entries):
    """Finished cards only: seller photo next to the white and black frame of the same index."""
    esc=lambda value:html.escape(str(value))
    def pic(url, caption):
        return f'<figure><img loading="lazy" src="{image_uri(url,560)}"><figcaption>{esc(caption)}</figcaption></figure>'
    done=[e for e in entries if e['status']=='done' and e['result'].get('images')]
    sections=[]
    for n,e in enumerate(done,1):
        r=e['result'];selected=r['analysis'].get('selected') or [0,0,0,0]
        rows=''.join('<div class="row">'+pic(r['source_photos'][str(selected[i])],f'Фото продавца {selected[i]+1}')
            +pic(r['images']['white'][i],f'Белая, кадр {i+1}')+pic(r['images']['black'][i],f'Чёрная, кадр {i+1}')+'</div>'
            for i in range(4))
        codes=' / '.join(r.get('vendor_codes',{}).values())
        sections.append(f'<section id="p{n}"><h2>{n}. {esc(r["text"]["title"])}</h2><p class="meta">{esc(codes)} · '
            f'<a href="{esc(r.get("source_url",""))}" target="_blank" rel="noopener">исходник на WB</a></p>{rows}</section>')
    nav=''.join(f'<a href="#p{i}">{i}</a>' for i in range(1,len(done)+1))
    document=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WB: готовые карточки</title>
<style>:root{{--bg:#f1f2f4;--card:#fff;--fg:#20232a;--mute:#6b7280;--cap:#eef0f2}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16181d;--card:#20232a;--fg:#e8eaee;--mute:#9aa1ad;--cap:#2a2e36}}}}
body{{font:15px/1.45 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--fg)}}main{{max-width:1200px;margin:auto;padding:16px}}
nav{{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;flex-wrap:wrap;gap:6px;z-index:1}}nav a{{padding:4px 10px;border-radius:8px;background:var(--card);color:inherit;text-decoration:none}}
section{{background:var(--card);border-radius:14px;padding:16px;margin:16px 0}}h2{{margin:0 0 4px;font-size:18px}}.meta{{margin:0 0 12px;color:var(--mute)}}.meta a{{color:inherit}}
.row{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:8px}}figure{{margin:0}}img{{width:100%;display:block;border-radius:8px 8px 0 0;aspect-ratio:3/4;object-fit:cover;background:var(--cap)}}
figcaption{{font-size:13px;padding:4px 8px;background:var(--cap);border-radius:0 0 8px 8px}}</style>
<main><h1>WB: готовые карточки</h1><p class="meta">Готовых принтов: {len(done)}. В каждой строке: фото продавца и два наших кадра с тем же номером.</p><nav>{nav}</nav>{''.join(sections)}</main></html>'''
    (out/'review-portable.html').write_text(document,encoding='utf-8')


@parsing_batch
async def main(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    state=out/'state.json';entries=read(state) if state.exists() else []
    env=read_env();storage=LocalStorage(out/'files')
    studio=Studio(SimpleNamespace(list=lambda **kw:[]),storage,env)
    if not entries:
        repo=JobRepository(Path(args.seed)/'jobs.db',timeout_sec=30)
        for j in repo.list(product='tee_wb',limit=100):
            if j.status==JobStatus.DONE and j.payload.get('kind')=='wb_card':
                entries.append({'id':j.id,'source':j.payload['source'],'result':j.result,'status':'done'})
        write(state,entries)
    repo=JobRepository(Path(args.search_run)/'jobs.db',timeout_sec=30)
    candidates=[]
    for j in repo.list(product='tee_wb',limit=100):
        candidates.extend(j.result.get('sources',[]))
    for capture in sorted(out.glob('search-*.json')):
        candidates.extend(read(capture))
    import printflow.wb_studio.infrastructure.wb.search as search
    async def generate(e):
        config=e.setdefault('config',studio.configuration(['white','black'],'source_redraw'))
        j=Job(id=e['id'],number=entries.index(e)+1,design_number=entries.index(e)+1,
              status=JobStatus.RUNNING,product='tee_wb',payload={'kind':'wb_card','theme':args.theme,'source':e['source'],'config':config},result=e.get('result',{}))
        def save(stage,result):
            e.update(stage=stage,result=copy.deepcopy(result));write(state,entries)
            print(e['source']['sku'],stage,flush=True)
        e['status']='running';write(state,entries)
        try:
            e['result']=await studio.card(j,save);e['status']='done';e.pop('error',None)
        except Exception as exc:
            e['status']='failed';e['error']=type(exc).__name__+': '+str(exc)
        write(state,entries);print(e['source']['sku'],e['status'],e.get('error',''),flush=True)
    # Resume only interrupted work; completed outputs and rejected sources stay intact.
    interrupted=[e for e in entries if e['status']=='running']
    for i in range(0,len(interrupted),3):await asyncio.gather(*(generate(e) for e in interrupted[i:i+3]))
    pending=[];seen={e['source']['sku'] for e in entries};queries=iter([args.theme,'футболка с принтом кот','футболка кот мем','футболка котики'])
    while sum(e['status']=='done' for e in entries)<args.count:
        if not candidates:
            try:query=next(queries)
            except StopIteration:break
            try:
                candidates=await search.discover(query,20)
                write(out/('search-'+uuid.uuid4().hex[:8]+'.json'),candidates)
            except Exception as exc:
                print('SEARCH ERROR',str(exc),flush=True);continue
        source=candidates.pop(0)
        if source['sku'] in seen:continue
        seen.add(source['sku'])
        e={'id':uuid.uuid4().hex,'source':source,'status':'parsing','result':{}}
        entries.append(e);write(state,entries);print('PARSING',source['sku'],flush=True)
        try:
            resolved=await search.resolve_product_urls([source['url']])
            if not resolved:raise RuntimeError('No gallery')
            e['source']=resolved[0];e['source']['sku']=source['sku'];e['status']='running'
        except Exception as exc:
            e.update(status='parse_failed',error=str(exc));write(state,entries)
            print('PARSE FAILED',source['sku'],str(exc),flush=True);continue
        pending.append(asyncio.create_task(generate(e)))
        if len(pending)>=min(3,args.count-sum(e['status']=='done' for e in entries)):
            await asyncio.gather(*pending);pending=[]
            print('COMPLETED',sum(e['status']=='done' for e in entries),'TARGET',args.count,flush=True)
    if pending:await asyncio.gather(*pending)
    report(out,entries)
    print('REPORT',out/'review-portable.html','DONE',sum(e['status']=='done' for e in entries),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='outputs/wb-redraw-v9-ten-20261025')
    parser.add_argument('--count',type=int,default=10)
    parser.add_argument('--theme',default='футболка с котом')
    parser.add_argument('--seed',default='outputs/wb-redraw-v9-live-second-20261025')
    parser.add_argument('--search-run',default='outputs/wb-redraw-v9-live-20261025')
    asyncio.run(main(parser.parse_args()))
