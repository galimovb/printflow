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
from printflow.wb_studio.infrastructure.wb.search import parsing_batch


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
    esc=lambda value:html.escape(str(value))
    def pic(url, caption, width=1000):
        return f'<figure><img loading="lazy" src="{image_uri(url,width)}"><figcaption>{esc(caption)}</figcaption></figure>'
    sections=[]
    done=[e for e in entries if e['status']=='done']
    for n,e in enumerate(done,1):
        r=e['result'];a=r['analysis'];source=e['source']
        body=f'<section id="card-{n}"><h2>{n}. {esc(r["text"]["title"])}</h2><p>Исходный артикул WB: {esc(source["sku"])}. Все изображения встроены в этот файл.</p>'
        if r.get('print_crop'):
            body+='<h3>Автоматически выделенная область принта на ткани</h3><div class="print">'+pic(r['print_crop'],'Эта область передаётся на извлечение, вместо всей страницы продавца')+'</div>'
            body+='<details><summary>Автоматические проверки</summary><pre>'+esc(json.dumps({'location':r.get('print_location'),'prints':r.get('print_checks'),'photos':r.get('photo_checks')},ensure_ascii=False,indent=2))+'</pre></details>'
        for color,label in [('white','Белая футболка'),('black','Чёрная футболка')]:
            body+=f'<h3>{label}: до → после</h3><div class="comparisons">'
            for i,index in enumerate(a['selected']):
                body+='<div class="pair">'+pic(r['source_photos'][str(index)],f'До: исходник {index+1}')+pic(r['images'][color][i],f'После: кадр {i+1}')+'</div>'
            body+='</div><h3>Извлечённый печатный принт</h3><div class="print">'+pic(r['print_variants'][color],label,1200)+'</div>'
            body+='<details><summary>Все 6 итоговых слайдов</summary><div class="gallery">'+''.join(pic(url,f'Слайд {i+1}',800) for i,url in enumerate(r['images'][color]))+'</div></details>'
        body+='<details><summary>Все исходные фотографии и результат отбора</summary><div class="gallery">'
        body+=''.join(pic(url,f'Исходник {int(i)+1}',700) for i,url in r['source_photos'].items())
        body+='</div><pre>'+esc(json.dumps(a['filter'],ensure_ascii=False,indent=2))+'</pre></details></section>'
        sections.append(body)
    failures=[e for e in entries if e['status'] in ('failed','parse_failed')]
    failed='<details><summary>Отклонённые и неудачные попытки: '+str(len(failures))+'</summary>'+''.join('<p>'+esc(e['source'].get('sku',''))+': '+esc(e.get('error',''))+'</p>' for e in failures)+'</details>'
    document='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WB — сравнение до и после</title>
<style>body{font:16px/1.5 system-ui;margin:0;background:#f1f2f4;color:#20232a}main{max-width:1600px;margin:auto;padding:24px}section{background:white;padding:24px;margin:28px 0;border-radius:16px}h1,h2,h3{line-height:1.2}figure{margin:0}img{width:100%;height:auto;display:block}figcaption{padding:8px;background:#eef0f2}.comparisons{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.gallery{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.print{max-width:500px;background:#ddd}details{margin:24px 0}summary{cursor:pointer;font-weight:600;padding:12px;background:#eef0f2}pre{white-space:pre-wrap}nav{display:flex;gap:12px;flex-wrap:wrap}@media(max-width:800px){.comparisons{grid-template-columns:1fr}.gallery{grid-template-columns:repeat(2,1fr)}main,section{padding:12px}}</style><main><h1>WB: исходники и перерисовка</h1>'''
    document+=f'<p>Готовых принтов: {len(done)}. По 2 цвета и 6 слайдов на цвет. Публикация WB отключена. Файл самодостаточный: интернет и дополнительные папки не нужны.</p><nav>'
    document+=''.join(f'<a href="#card-{i}">Принт {i}</a>' for i in range(1,len(done)+1))+'</nav>'+''.join(sections)+failed+'</main></html>'
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
