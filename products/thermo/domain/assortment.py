"""One source of truth for the contents, gallery copy and listing."""
import copy
import math


def sizes(product):
    options = product.get('assortment', {})
    mode = options.get('mode', 'set')
    if mode not in ('single', 'set'):
        raise ValueError('Thermo assortment mode must be single or set')
    items = copy.deepcopy(options.get('sizes') or (
        [{'key': 'single', 'label': 'РАЗМЕР ПРИНТА', 'size_cm': product.get('single_size_cm', [21, 29.7])}]
        if mode == 'single' else product['set_sizes']))
    if (mode == 'single' and len(items) != 1) or (mode == 'set' and not 2 <= len(items) <= 6):
        raise ValueError('Thermo requires one single size or 2–6 set sizes')
    previous = 0
    keys = set()
    for index, item in enumerate(items):
        dims = item.get('size_cm', [])
        if len(dims) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in dims):
            raise ValueError('Thermo size must contain two positive finite centimetre values')
        area = math.prod(dims)
        if area <= previous:
            raise ValueError('Thermo sizes must be ordered from small to large')
        previous = area
        item.setdefault('key', f'size-{index+1}')
        item.setdefault('label', 'РАЗМЕР ПРИНТА' if len(items) == 1 else f'РАЗМЕР {index+1}')
        if item['key'] in keys:
            raise ValueError('Thermo size keys must be unique')
        keys.add(item['key'])
    return items


def caption(item):
    return ' × '.join(dimension_text(v) for v in item['size_cm']) + ' см'


def dimension_text(value):
    return f'{value:.1f}'.rstrip('0').rstrip('.').replace('.', ',')


def resolve_artwork(product, pixel_size):
    """Keep the configured width; derive height from the cropped artwork, without rounding geometry."""
    result = copy.deepcopy(product)
    if result.get('assortment', {}).get('mode') != 'single' or result.get('single_sizing') != 'width_proportional':
        return result
    width_px, height_px = pixel_size
    if min(width_px, height_px) <= 0:
        raise ValueError('Empty thermo artwork')
    width_cm = float(result.get('single_width_cm', 21))
    if not math.isfinite(width_cm) or width_cm <= 0:
        raise ValueError('Thermo width must be positive and finite')
    dimensions = [width_cm, width_cm * height_px / width_px]
    result['assortment']['sizes'] = [{'key':'single','label':'РАЗМЕР ПРИНТА','size_cm':dimensions}]
    result['generation']['print_area_cm'] = dimensions
    result['resolved_print'] = {'pixels':list(pixel_size),'size_cm':dimensions,'sizing':'width_proportional'}
    return listing_config(result)


def copy_for(items):
    count = len(items)
    single = count == 1
    return {
        'pill': 'Один принт — один размер' if single else f'Один дизайн — {count} размера' if count < 5 else f'Один дизайн — {count} размеров',
        'badge': 'В КОМПЛЕКТЕ 1 ШТ.' if single else f'В НАБОРЕ {count} ШТ.',
        'subtitle': caption(items[0]) if single else 'По одному принту каждого размера',
        'contents_title': 'ВАШ ПРИНТ' if single else 'СОСТАВ НАБОРА',
        'contents_sub': 'ОДИН РАЗМЕР' if single else f'{count} РАЗМЕРА' if count < 5 else f'{count} РАЗМЕРОВ',
    }


def configure(product, mode=None, dimensions=None):
    result = copy.deepcopy(product)
    options = result.setdefault('assortment', {})
    if mode:
        options['mode'] = mode
        options.pop('sizes', None)
    if dimensions:
        options['sizes'] = [{'size_cm': list(pair)} for pair in dimensions]
    sizes(result)
    return result


def parse_dimensions(value):
    try:
        pair = [float(v.replace(',', '.')) for v in value.lower().replace('×', 'x').split('x')]
        if len(pair) != 2:
            raise ValueError()
        return pair
    except ValueError as exc:
        import argparse
        raise argparse.ArgumentTypeError('Укажите ширину x высоту в см, например 13x19') from exc


def add_arguments(parser):
    parser.add_argument('--mode', choices=['single', 'set'], help='one print or one design in several sizes')
    parser.add_argument('--sizes', nargs='+', type=parse_dimensions, help='centimetres, small to large: 6.5x9.5 10x14.6 13x19')


def listing_config(product):
    result = copy.deepcopy(product)
    items = sizes(result)
    words = copy_for(items)
    count = len(items)
    ozon = result['ozon']
    suffix = caption(items[0]) + ', 1 шт.' if count == 1 else f'набор {count} шт., {count} размера' if count < 5 else f'набор {count} шт., {count} размеров'
    noun = 'Термонаклейка' if count == 1 else 'Термонаклейки'
    ozon['name_template'] = noun + ' для одежды {design}, ' + suffix
    ozon['name_fallback'] = noun + ' для одежды и аксессуаров, ' + suffix
    contents = ('Одна термонаклейка: ' if count == 1 else f'Набор из {count} термонаклеек с одинаковым рисунком: ') + ', '.join(map(caption, items)) + '.'
    ozon['description_template'] = contents + ' Переносится утюгом на подходящую ткань. Вещи на фотографиях показаны для примера и в комплект не входят. Следуйте инструкции к плёнке и ярлыку ткани.'
    ozon.setdefault('wishes', {})['Количество в упаковке'] = str(count)
    ozon['rich']['features'] = [
        {'title': 'ПЕРЕНОС УТЮГОМ', 'text': 'Следуйте инструкции к плёнке и ярлыку ткани.'},
        {'title': words['pill'].upper(), 'text': contents},
    ]
    return result
