"""Generate all thermo blank templates in one command; export all six empty card layouts.

    python -m printflow.products.thermo.scripts.generate_blanks --dry-run
    python -m printflow.products.thermo.scripts.generate_blanks
    python -m printflow.products.thermo.scripts.generate_blanks --check-only

GPT creates complete blue card scenes with the shirt and tote already in place.
A third empty background is reused for the other four layouts; code adds exact text. Existing working templates are replaced only after all new
scenes validate, with backups. No S3, Ozon or other product files are touched.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile

import numpy as np
from scipy import ndimage
from PIL import Image, ImageFilter

from printflow.config import read_env
from printflow.products.thermo.product import Thermo
from printflow.products.thermo.infrastructure.gallery.renderer import compose, ThermoGalleryRenderer
from printflow.products.thermo.domain.assortment import add_arguments, configure, listing_config

PRODUCT = Thermo()
STYLE = (
    'Create one reusable full-frame vertical 3:4 marketplace card BACKGROUND TEMPLATE. '
    'Canvas 1200x1600, modern clean light grey-blue gradient #F1F8FF to #CBDEF3, subtle '
    'large very pale blue abstract corner curves. Identical calm neutral studio light. '
    'LAYOUT CRITICAL: the whole TOP 30 percent (y=0..480 pixels) and BOTTOM 15 percent must remain empty blue background for '
    'headlines and badges added later by code. Absolutely no part of a garment or handle may enter the top 480 pixels. No text, numbers, logos, labels, icons, '
    'frames, panels, watermark, green chromakey, checkerboard, model, person, mannequin, '
    'furniture, wall, floor or photograph boundary. Compose directly into this full blue '
    'card, NOT a separate cutout or inset photo. '
)
SUBJECTS = {
    'background': (
        'Only the empty blue gradient background with subtle corner shapes, no objects. '
        'The center must also be empty for a heat-transfer artwork or instruction panels.'
    ),
    'accents': (
        'A coordinated top-down flat lay of THREE completely blank unprinted items: white cotton '
        'T-shirt left-center, beige tote right, small beige zip pouch lower-left. Gentle natural shadows. '
        'Detailed premium editorial photography: clearly visible cotton weave, stitching, zipper, '
        'handles, natural depth and subtle seam shadows. Tasteful sunglasses at the upper-right edge, '
        'neutral notebook and gold pen lower-right, a little eucalyptus along the lower-left edge. '
        'Large shirt is the hero, tote is visibly narrower, small pouch in front; use the same '
        'pixel-per-centimetre scale for all three objects. Do not simplify the scene into tiny floating cutouts. '
        'Mostly smooth professionally steamed shirt front, only subtle folds at seams and hem. '
        'No deep wrinkles, no crumpled fabric. Keep ALL items below y=480 and above y=1360. '
        'Shirt blank BODY fabric surface quadrilateral, normalized coordinates: '
        '(0.18,0.39),(0.54,0.39),(0.55,0.70),(0.18,0.71), physical 52x58 cm. '
        'Tote BODY surface (0.60,0.475),(0.94,0.518),(0.89,0.812),(0.54,0.76), physical 34x38 cm. '
        'Pouch surface (0.08,0.773),(0.25,0.73),(0.29,0.823),(0.12,0.85), physical 22x14 cm. '
        'These are complete fabric planes, NOT print sizes. Keep them visible and unobstructed. '
        'No prints or typography anywhere. '
        'Keep editorial props at edges only, no objects covering the fabric print panels.'
    ),
    'shirt': (
        'Generate and place a photorealistic blank white cotton crewneck short-sleeve '
        'T-shirt directly into the card center, straight front view. Entire shirt including '
        'collar, sleeves and hem fits within x=16..84 percent and y=32..83 percent of card. Top of collar at pixel y=512, NOT higher. Make the shirt smaller if necessary to leave the entire top third EMPTY. '
        'Torso at chest level spans x=28..72 percent (44 percent of card width), equivalent '
        'to a 52 cm body width. Blank flat printing panel centered at x=50, y=54 percent. '
        'No front pocket, no existing print. Professionally steamed mostly smooth front, '
        'no crumpling or deep creases. Realistic cotton texture, gentle folds near '
        'seams only. Background immediately surrounds the shirt, including sleeve gaps.'
    ),
    'shopper': (
        'Generate and place a photorealistic blank natural ivory cotton tote bag directly '
        'into the center of the blue card, straight front view. Complete handles start at '
        'y=32 percent (pixel y=512), bag body starts at y=49 percent and bottom ends at y=83 percent. Make the handles shorter if necessary, all handles below y=480 pixels. '
        'Body spans x=26..74 percent (48 percent of card width), physical body size 34x38 cm. '
        'Two upright handles with open blue space inside. Flat smooth empty front panel '
        'centered at x=50, y=67 percent. Natural cotton weave and subtle seam shadows. '
        'No pocket, contents, logos, prints, hook or backdrop photo. No cast shadow outside.'
    ),
}


def build_jobs(names, model, size, quality):
    return [dict(prompt=STYLE+SUBJECTS[name], model=model, size=size, quality=quality,
                 output_format='png', out=f'{name}.png') for name in names]


def validate_asset(image, name):
    if min(image.size) < 512 or abs(image.width/image.height-.75) > .015:
        raise ValueError(f'{name}: expected a full 3:4 card background at adequate resolution')
    arr=np.asarray(image.convert('RGB'),dtype=np.float32)
    if arr.std() < 2:
        raise ValueError(f'{name}: empty solid image instead of a generated card scene')
    if name == 'accents':
        return {'size':list(image.size),'mode':image.mode,'kind':'three-item-flatlay'}
    if name != 'background':
        region=arr[int(image.height*.51):int(image.height*.76),int(image.width*.35):int(image.width*.65)]
        # A pale garment must be present in the intended front-panel area.
        neutral=(region.min(2)>140)&((region.max(2)-region.min(2))<45)
        if neutral.mean() < .35:
            raise ValueError(f'{name}: no light blank garment in the print area')
    if name != 'background':
        garment=((arr.min(2)>180)&(arr[:,:,0]-arr[:,:,2]>-4)&((arr.max(2)-arr.min(2))<13)) if name=='shirt' else ((arr[:,:,0]-arr[:,:,2]>6)&(arr[:,:,0]>160)&((arr.max(2)-arr.min(2))<70))
        labels,_=ndimage.label(garment)
        core=labels[int(image.height*.51):int(image.height*.72),int(image.width*.42):int(image.width*.58)]
        ids,counts=np.unique(core[core>0],return_counts=True)
        if not len(ids):
            raise ValueError(f'{name}: no coherent garment in print area')
        garment=labels==ids[counts.argmax()]
        upper=garment[:int(image.height*.26),int(image.width*.12):int(image.width*.88)]
        if upper.mean() > .005:
            raise ValueError(f'{name}: garment overlaps the headline area; regenerate this scene')
    return {'size':list(image.size),'mode':image.mode,'kind':'full-card-scene'}


def prepare_asset(raw_path, target, name):
    with Image.open(raw_path) as source:
        image=source.convert('RGB')
    report=validate_asset(image,name)
    image.resize((1200,1600),Image.Resampling.LANCZOS).save(target)
    return report


def extract_garment(scene_path, target, name):
    """Derive current cutouts from generated full scenes, never reuse old garments."""
    with Image.open(scene_path) as image:
        image=image.convert('RGBA')
    a=np.asarray(image.convert('RGB'),dtype=np.float32)
    if name=='shirt':
        mask=(a.min(2)>130)&(a[:,:,0]-a[:,:,2]>-4)&(a.max(2)-a.min(2)<42)
    else:
        mask=(a[:,:,0]>145)&(a[:,:,0]-a[:,:,2]>5)&(a.max(2)-a.min(2)<80)
    components,_=ndimage.label(mask)
    h,w=mask.shape
    core=components[int(h*.52):int(h*.73),int(w*.43):int(w*.57)]
    ids,counts=np.unique(core[core>0],return_counts=True)
    if not len(ids):
        raise ValueError(f'{name}: cannot extract a coherent blank garment')
    mask=components==ids[counts.argmax()]
    mask=ndimage.binary_closing(mask,iterations=2)
    alpha=Image.fromarray((mask*255).astype('uint8')).filter(ImageFilter.GaussianBlur(.55))
    image.putalpha(alpha)
    image.save(target)


def export_layouts(config, templates_dir, output, refresh_mockups=True):
    calibration={}
    if refresh_mockups:
        for name,spec in config['gallery']['mockups'].items():
            extract_garment(templates_dir/f'{name}-scene.png',templates_dir/spec['template'],name)
            calibration[name]={'reference_width_cm':52 if name=='shirt' else 34,
                'reference_width_fraction':.44 if name=='shirt' else .48,
                'center':[.5,.54] if name=='shirt' else [.5,.67]}
        (templates_dir/'mockup-calibration.json').write_text(json.dumps(calibration,indent=2),encoding='utf-8')
    cards = compose(Image.new('RGBA', (2, 2)), config, templates_dir)
    dst = output/'cards'
    dst.mkdir(parents=True, exist_ok=True)
    preview = Image.new('RGB', (900, 800), (235, 243, 253))
    for i, (name, image) in enumerate(cards.items()):
        image.save(dst/f'{name}.png')
        preview.paste(image.resize((300, 400), Image.Resampling.LANCZOS), ((i%3)*300, (i//3)*400))
    preview.save(output/'blank-preview.jpg', quality=94)
    return list(cards)


def export_ready(config,templates_dir,output,print_path):
    """The same command optionally applies an artwork through the production renderer."""
    data=print_path.read_bytes()
    from printflow.products.thermo.infrastructure.gallery.geometry import load_print
    from printflow.products.thermo.domain.assortment import resolve_artwork
    import io
    config=resolve_artwork(config,load_print(io.BytesIO(data)).size)
    (output/'resolved-product.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    renderer=ThermoGalleryRenderer(config,templates_dir)
    folder=output/'ready';folder.mkdir(parents=True,exist_ok=True)
    sheet=Image.new('RGB',(1200,1600),(235,243,253))
    for i,(name,image) in enumerate(renderer.compose_print(data,'main').items()):
        image.save(folder/f'{name}.png')
        sheet.paste(image.resize((400,534),Image.Resampling.LANCZOS),((i%3)*400,(i//3)*534))
    sheet.crop((0,0,1200,1068)).save(output/'ready-preview.jpg',quality=95)
    files=renderer.render(data,'main')
    with zipfile.ZipFile(output/'ready-six-jpg.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name,jpeg in files:
            (folder/f'{name}.jpg').write_bytes(jpeg)
            archive.writestr(f'{name}.jpg',jpeg)
    return str(folder)


def cli_path(explicit=None):
    if explicit:
        return Path(explicit)
    home = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))
    return home/'skills/.system/imagegen/scripts/image_gen.py'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', nargs='+', choices=list(SUBJECTS))
    parser.add_argument('--out-dir', type=Path, default=PRODUCT.templates_dir)
    parser.add_argument('--output-dir', type=Path, help='separate destination for assembled cards; templates stay in --out-dir')
    add_arguments(parser)
    parser.add_argument('--model', default=None)
    parser.add_argument('--resume-from',type=Path,help='reuse raw GPT outputs from a previous staging folder; no new API calls')
    parser.add_argument('--size', default='1200x1600')
    parser.add_argument('--quality', default='high', choices=['low','medium','high','auto'])
    parser.add_argument('--dry-run', action='store_true', help='write exact GPT requests; no network or template replacement')
    parser.add_argument('--check-only', action='store_true', help='validate current templates and render all six blank layouts; no GPT')
    parser.add_argument('--print',dest='print_path',type=Path,help='also apply this PNG to all six cards and export Ozon JPEGs')
    parser.add_argument('--imagegen-cli', type=Path, help='path to the installed imagegen skill CLI')
    args = parser.parse_args(argv)
    if args.dry_run and args.check_only:
        parser.error('--dry-run and --check-only cannot be combined')
    if args.print_path and not args.print_path.is_file():
        parser.error('Print file does not exist: '+str(args.print_path))
    env = read_env()
    model = args.model or env.get('THERMO_IMAGE_MODEL', 'gpt-image-2')
    names = list(dict.fromkeys(args.only or SUBJECTS))
    try:
        config = listing_config(configure(PRODUCT.config, args.mode, args.sizes))
    except ValueError as exc:
        parser.error(str(exc))
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    output = (args.output_dir or out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output/'resolved-product.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    jobs = build_jobs(names, model, args.size, args.quality)
    if args.dry_run:
        path = out/'generation-plan.json'
        path.write_text(json.dumps({'jobs':jobs, 'cards':6}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(f'Dry run: {len(jobs)} GPT requests + 6 card layouts; plan: {path}', flush=True)
        return 0
    if args.check_only:
        reports = {}
        for name in SUBJECTS:
            with Image.open(out/f'{name}-scene.png') as image:
                reports[name] = validate_asset(image, name)
        layouts = export_layouts(config, out, output, refresh_mockups=False)
        if args.print_path:
            export_ready(config,out,output,args.print_path)
        print(json.dumps({'checked':reports, 'cards':layouts}, ensure_ascii=False), flush=True)
        return 0
    cli = cli_path(args.imagegen_cli)
    if not args.resume_from and not cli.is_file():
        parser.error('Imagegen CLI not found; install the imagegen skill or pass --imagegen-cli')
    if not args.resume_from and not env.get('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY is not configured')
    # Stage every result: a failed run cannot destroy the approved templates.
    stage=args.resume_from.resolve() if args.resume_from else out/'_generation'/uuid.uuid4().hex
    stage.mkdir(parents=True,exist_ok=bool(args.resume_from))
    raw=stage/'raw'
    raw.mkdir(exist_ok=bool(args.resume_from))
    manifest = stage/'jobs.jsonl'
    manifest.write_text(''.join(json.dumps(job,ensure_ascii=False)+'\n' for job in jobs), encoding='utf-8')
    subprocess_env = os.environ.copy()
    for key in ('OPENAI_API_KEY','OPENAI_BASE_URL'):
        if env.get(key):
            subprocess_env[key] = env[key]
    subprocess_env['PYTHONIOENCODING'] = 'utf-8'
    command = [sys.executable,str(cli),'generate-batch','--input',str(manifest),
               '--out-dir',str(raw),'--concurrency','1','--max-attempts','2','--no-augment']
    print(f'Generating {len(names)} thermo assets via {model}; stage: {stage}', flush=True)
    if args.resume_from:
        for name in names:
            if not (raw/f'{name}.png').is_file():
                parser.error(f'Missing staged output: {raw/name}')
        print('Reusing existing GPT outputs; no API calls',flush=True)
    else:
        subprocess.run(command, env=subprocess_env, check=True)
    reports = {}
    for name in SUBJECTS:
        filename = f'{name}-scene.png'
        if name in names:
            reports[name] = prepare_asset(raw/f'{name}.png',stage/filename,name)
            (stage/f'{name}.prompt.txt').write_text(STYLE+SUBJECTS[name]+'\n',encoding='utf-8')
        elif not (stage/filename).is_file():
            shutil.copy2(out/filename,stage/filename)
    layouts = export_layouts(config, stage, stage)
    backup = out/'_backups'/stage.name
    backup.mkdir(parents=True)
    for name in names:
        filename = f'{name}-scene.png'
        if (out/filename).is_file():
            shutil.copy2(out/filename,backup/filename)
        shutil.copy2(stage/filename,out/filename)
        shutil.copy2(stage/f'{name}.prompt.txt',out/f'{Path(filename).stem}.prompt.txt')
    shutil.copytree(stage/'cards',out/'cards',dirs_exist_ok=True)
    for spec in config['gallery']['mockups'].values():
        shutil.copy2(stage/spec['template'],out/spec['template'])
    shutil.copy2(stage/'mockup-calibration.json',out/'mockup-calibration.json')
    shutil.copy2(stage/'blank-preview.jpg',out/'blank-preview.jpg')
    report = {'model':model,'assets':reports,'cards':layouts,'backup':str(backup)}
    (out/'generation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.print_path:
        export_ready(config,out,output,args.print_path)
    if output != out:
        export_layouts(config,out,output)
    print(f'OK: {len(names)} GPT assets + {len(layouts)} blank card layouts: {out}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
