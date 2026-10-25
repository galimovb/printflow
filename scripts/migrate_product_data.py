"""Move legacy product data into SM_DATA_DIR/<product> without rewriting contents.

python -m printflow.scripts.migrate_product_data             # show plan
python -m printflow.scripts.migrate_product_data --apply     # migrate

Shared jobs.db is never opened or moved. All conflicts are checked before any move.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from printflow.config import load_app_settings, product_data_dir
from printflow.products import PRODUCTS


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def migration_plan(data_root):
    root=Path(data_root).resolve()
    plan=[]
    def add(source,target):
        source,target=Path(source),Path(target)
        if not source.exists(): return
        if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
            raise ValueError('Migration path escapes SM_DATA_DIR')
        if source.is_symlink() or (hasattr(source,'is_junction') and source.is_junction()):
            raise ValueError(f'Linked migration path rejected: {source}')
        if source.is_dir():
            for child in sorted(source.iterdir()): add(child,target/child.name)
        else:
            if target.exists(): raise FileExistsError(f'Refusing to overwrite existing data: {target}')
            plan.append({'source':str(source),'target':str(target),'sha256':digest(source),'bytes':source.stat().st_size})
    for name in PRODUCTS:
        target=product_data_dir(root,name)
        for kind in ('ideas','preview','guides'):
            add(root/kind/name,target/kind)
        add(root/'reports'/f'sources_{name}.csv',target/'reports'/'sources.csv')
        old_reports=root/'reports'
        if old_reports.is_dir():
            for source in sorted(old_reports.iterdir()):
                if source.name.startswith(name+'_') or source.name.startswith(f'analyze_{name}_') or source.name.startswith(f'classify_{name}_'):
                    add(source,target/'reports'/source.name)
    # Historical helper bytecode belongs to the same shopper analysis reports.
    add(root/'reports'/'__pycache__',root/'shopper'/'reports'/'__pycache__')
    for source in sorted(root.glob('jobs.backup-*.db')):
        add(source,root/'backups'/source.name)
    destinations=[item['target'] for item in plan]
    if len(set(destinations))!=len(destinations): raise ValueError('Duplicate migration destinations')
    return plan


def migrate(data_root,apply=False):
    root=Path(data_root).resolve()
    plan=migration_plan(root)
    if not apply: return plan
    for name in PRODUCTS:
        for kind in ('ideas','preview','guides','reports'):
            (product_data_dir(root,name)/kind).mkdir(parents=True,exist_ok=True)
    if plan:
        log=root/'migrations'/f'product-data-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json'
        log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for item in plan:
        source,target=Path(item['source']),Path(item['target'])
        # Recheck paths and contents immediately before moving; no recursive removal.
        if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
            raise ValueError('Migration path changed')
        if digest(source)!=item['sha256']: raise RuntimeError(f'Source changed during migration: {source}')
        target.parent.mkdir(parents=True,exist_ok=True)
        source.rename(target)
        if digest(target)!=item['sha256']: raise RuntimeError(f'Moved content failed verification: {target}')
    for kind in ('ideas','preview','guides','reports'):
        legacy=root/kind
        if legacy.is_dir():
            for directory in sorted((p for p in legacy.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
                if directory.resolve().is_relative_to(root) and not any(directory.iterdir()): directory.rmdir()
            if not any(legacy.iterdir()): legacy.rmdir()
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    root=args.data_dir or load_app_settings().data_dir
    plan=migrate(root,args.apply)
    print(json.dumps({'applied':args.apply,'files':len(plan),'bytes':sum(item['bytes'] for item in plan),'root':str(root),'moves':plan},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
