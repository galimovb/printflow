"""Queue WB themes or already parsed source photos. No publication is implicit."""
import argparse
import json
from pathlib import Path
import httpx
from printflow.config import read_env,load_app_settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--theme',help='one WB search query')
    inputs.add_argument('--themes',type=Path,help='UTF-8 file, one search query per line')
    inputs.add_argument('--url',action='append',help='WB product URL; may be repeated up to 20 times')
    inputs.add_argument('--urls',type=Path,help='UTF-8 file with WB product URLs, one per line')
    inputs.add_argument('--sources',type=Path,help='JSON {theme,sources:[{url,image,title}]} from an existing parser')
    parser.add_argument('--algorithm',choices=['standard','source_redraw'],default=None)
    parser.add_argument('--design-limit',type=int,choices=range(1,21),help='generate only the first N discovered prints; e.g. 1 for a pilot')
    parser.add_argument('--limit',type=int,choices=[10,20],default=10)
    parser.add_argument('--colors',nargs='+',choices=['white','black'],default=None)
    parser.add_argument('--api',default=None)
    parser.add_argument('--local',action='store_true',help='generate on this computer; no API server, S3 or WB publication')
    parser.add_argument('--out',type=Path,default=Path('outputs/wb-studio-local'))
    args=parser.parse_args()
    if args.sources and args.design_limit:parser.error('--design-limit is for search requests')
    env=read_env()
    body={} if args.url or args.urls else json.loads(args.sources.read_text(encoding='utf-8')) if args.sources else {
        'themes':[args.theme] if args.theme else args.themes.read_text(encoding='utf-8').splitlines(),'limit':args.limit,
        'design_limit':args.design_limit}
    if args.url or args.urls:
        body={'urls':args.url or [x.strip() for x in args.urls.read_text(encoding='utf-8-sig').splitlines() if x.strip()]}
    body['algorithm']=args.algorithm or ('source_redraw' if args.url or args.urls else body.get('algorithm','standard'))
    from printflow.wb_studio.config import default_colors
    body['colors']=args.colors or default_colors(env)
    if args.local:
        import asyncio
        from printflow.wb_studio.infrastructure.local import generate
        from printflow.domain.errors import PermanentError
        try:
            asyncio.run(generate(body,args.out,env))
        except PermanentError as exc:
            parser.exit(2,str(exc)+"\n")
        except KeyboardInterrupt:
            parser.exit(130,'Остановлено пользователем. Готовые шаги сохранены; повторите команду для продолжения.\n')
        except Exception as exc:
            parser.exit(2,f'Не удалось завершить локальный запуск: {type(exc).__name__}: {exc}\n')
        errors_path=args.out/'errors.json'
        if errors_path.exists() and json.loads(errors_path.read_text(encoding='utf-8')):
            parser.exit(1,f'Есть ошибки. Подробности: {errors_path}\n')
        return
    token=env.get('PRINTFLOW_WB_API_TOKEN','')
    if not token:parser.error('PRINTFLOW_WB_API_TOKEN is not set')
    with httpx.Client(base_url=args.api or load_app_settings().api_url,trust_env=False,timeout=60) as client:
        try:
            response=client.post('/api/v1/wb-studio/'+('urls' if args.url or args.urls else 'sources' if args.sources else 'campaigns'),json=body,
                headers={'Authorization':'Bearer '+token})
        except httpx.ConnectError:
            parser.exit(2,'PrintFlow API не запущен. Добавьте --local для генерации без сервера либо запустите python -m printflow.\n')
        response.raise_for_status();print(json.dumps(response.json(),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
