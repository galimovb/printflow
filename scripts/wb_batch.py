"""Enqueue mass WB generation in the application queue. --local runs the same worker with local storage."""
import argparse,asyncio,json
from pathlib import Path
import httpx
from printflow.config import read_env,load_app_settings
from printflow.wb_studio.config import default_colors,merge_designs

def main():
 env=read_env();p=argparse.ArgumentParser(description=__doc__)
 inputs=p.add_mutually_exclusive_group(required=True);inputs.add_argument('--theme');inputs.add_argument('--themes',type=Path)
 p.add_argument('--algorithm',choices=['standard','source_redraw'],default='standard')
 p.add_argument('--count',type=int,choices=range(1,21),default=10,help='prints per theme; merging size is PRINTFLOW_WB_MERGE_DESIGNS')
 p.add_argument('--limit',type=int,choices=[10,20],default=20)
 p.add_argument('--colors',nargs='+',choices=['white','black'],default=None)
 p.add_argument('--local',action='store_true',help='same persistent queue, local PNG/JPEG storage, no S3 and no WB publication')
 p.add_argument('--out',type=Path,default=Path('outputs/wb-batch-local'))
 p.add_argument('--concurrency',type=int,choices=range(1,31),help='local worker override; default PRINTFLOW_WB_WORKERS')
 p.add_argument('--api',default=None)
 args=p.parse_args()
 if args.count>args.limit:p.error('--count не может быть больше --limit')
 themes=[args.theme] if args.theme else args.themes.read_text(encoding='utf-8-sig').splitlines()
 themes=list(dict.fromkeys(t.strip() for t in themes if t.strip()))
 if not themes:p.error('Укажите хотя бы одну тему')
 body={'algorithm':args.algorithm,'themes':themes,'limit':args.limit,'design_limit':args.count,'colors':args.colors or default_colors(env)}
 print('Цвета:',', '.join(body['colors']),'Принтов в группе:',merge_designs(env))
 if args.local:
  from printflow.wb_studio.infrastructure.local import generate
  if args.concurrency:env={**env,'PRINTFLOW_WB_WORKERS':str(args.concurrency)}
  try:asyncio.run(generate(body,args.out,env))
  except KeyboardInterrupt:p.exit(130,'Остановлено. Очередь и промежуточные этапы сохранены.\n')
  errors=args.out/'errors.json'
  if errors.exists() and json.loads(errors.read_text(encoding='utf-8')):p.exit(1,f'Не все задачи готовы. Подробности: {errors}\n')
  return
 if args.concurrency:p.error('--concurrency применяется только с --local; для общей очереди задайте PRINTFLOW_WB_WORKERS')
 token=env.get('PRINTFLOW_WB_API_TOKEN','')
 if not token:p.error('Не задан PRINTFLOW_WB_API_TOKEN — токен входа в приложение')
 try:
  with httpx.Client(base_url=args.api or load_app_settings().api_url,trust_env=False,timeout=60) as client:
   response=client.post('/api/v1/wb-studio/campaigns',json=body,headers={'Authorization':'Bearer '+token})
   response.raise_for_status();data=response.json()
 except httpx.ConnectError:p.exit(2,'PrintFlow API не запущен. Запустите python -m printflow либо добавьте --local.\n')
 print(json.dumps(data,ensure_ascii=False,indent=2));print('Задачи поставлены в общую очередь. Просмотр: /studio/wb. Публикация WB запускается отдельно.')
if __name__=='__main__':main()
