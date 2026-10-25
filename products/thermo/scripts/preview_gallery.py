"""Local preview of the production thermo renderer, without S3, AI or Ozon."""
import argparse
from pathlib import Path
from PIL import Image
from printflow.products.thermo.product import Thermo
from printflow.config import load_app_settings
from printflow.products.thermo.domain.assortment import add_arguments, configure, listing_config


def main():
    product = Thermo()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print', dest='print_path', type=Path, default=product.directory/'assets/example-print.png')
    parser.add_argument('--out', type=Path, default=load_app_settings().product_data_dir(product.name)/'preview')
    add_arguments(parser)
    args = parser.parse_args()
    try:
        product._config = listing_config(configure(product.config, args.mode, args.sizes))
    except ValueError as exc:
        parser.error(str(exc))
    args.out.mkdir(parents=True, exist_ok=True)
    renderer = product.gallery()
    composed = renderer.compose_print(args.print_path.read_bytes(), 'main')
    sheet = Image.new('RGB', (900, 800), (235, 243, 253))
    for i, (name, im) in enumerate(composed.items()):
        im.save(args.out/f'{name}.png')
        sheet.paste(im.resize((300, 400), Image.Resampling.LANCZOS), ((i%3)*300, (i//3)*400))
    sheet.save(args.out/'preview.jpg', quality=95)
    import zipfile
    with zipfile.ZipFile(args.out/'thermo-cards.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in composed:
            archive.write(args.out/f'{name}.png', f'{name}.png')
    print(args.out.resolve())

if __name__ == '__main__':
    main()
