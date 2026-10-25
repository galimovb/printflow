"""Prepare the two shared final slides once; listing generation only loads these PNGs."""
import json
import uuid
import argparse
import shutil
from pathlib import Path
from printflow.wb_studio.infrastructure.rendering.info_slides import build_info_slide,information_signature,INFORMATION_DIR
from printflow.wb_studio.config import load_config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit',type=Path)
    parser.add_argument('--size',type=Path)
    parser.add_argument('--rebuild',action='store_true',help='explicitly replace imported user slides with generated layouts')
    args=parser.parse_args()
    if bool(args.fit)!=bool(args.size):parser.error('--fit and --size must be supplied together')
    manifest_path=INFORMATION_DIR/'manifest.json'
    if not args.fit and not args.rebuild and manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding='utf-8')).get('source')=='user':
            print('Using imported user slides; no changes:',INFORMATION_DIR)
            return
    config=load_config()
    stage=INFORMATION_DIR.parent/('_information-'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    for color in ('white','black'):
        (stage/color).mkdir()
        for index,name in ((4,'05-fit.png'),(5,'06-size.png')):
            if args.fit:shutil.copyfile(args.fit if index==4 else args.size,stage/color/name)
            else:(stage/color/name).write_bytes(build_info_slide(index,color,config))
    manifest={'signature':information_signature(config),'source':'user' if args.fit else 'generated'}
    (stage/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    backup=None
    if INFORMATION_DIR.exists():
        backup=INFORMATION_DIR.with_name('information-backup-'+uuid.uuid4().hex[:8])
        INFORMATION_DIR.rename(backup)
    try:stage.rename(INFORMATION_DIR)
    except BaseException:
        if backup:backup.rename(INFORMATION_DIR)
        raise
    print('Prepared shared slides:',INFORMATION_DIR)


if __name__=='__main__':main()
