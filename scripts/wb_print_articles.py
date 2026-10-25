"""Add article-named S3 print objects for completed WB cards, without generation."""
import asyncio,json
from pathlib import Path
from printflow.container import AppContainer
from printflow.domain.models import JobKind,JobStatus
async def main():
 app=AppContainer();studio=app.wb_studio;repo=app.job_repository
 jobs=[j for j in repo.list(product='tee_wb',limit=1000) if j.kind==JobKind.WB_CARD and j.status==JobStatus.DONE and j.result.get('print')]
 semaphore=asyncio.Semaphore(4);results=[]
 async def one(job):
  async with semaphore:
   def save(stage,result):repo.save_progress(job.id,stage=stage,result=result)
   aliases=await studio.save_article_prints(job,job.result,save)
   repo.save_progress(job.id,stage=job.stage,result=job.result)
   results.append({'job':job.id,'vendor_codes':job.result['vendor_codes'],'article_prints':aliases})
   print(job.id[:8],job.result['vendor_codes'],flush=True)
 await asyncio.gather(*(one(job) for job in jobs))
 out=Path('outputs/wb-article-print-backfill.json');out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Done:',len(results),'cards,',sum(len(r['article_prints']) for r in results),'article PNGs',flush=True)
if __name__=='__main__':asyncio.run(main())
