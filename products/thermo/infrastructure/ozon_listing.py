"""Thermo listing on the shared single-variant Ozon payload builder."""
from printflow.domain.errors import PermanentError
from printflow.services.ozon.listing import build_items as single_variant_items


def build_items(article, images, product, product_name=None, group=None, design=None):
    from ..domain.assortment import listing_config
    return single_variant_items(article, images, listing_config(product), product_name, group, design)


def validate_publication(product):
    from ..domain.assortment import sizes
    ozon = product['ozon']
    prepared_count = ozon.get('prepared_assortment_count')
    if prepared_count is not None and prepared_count != len(sizes(product)):
        raise PermanentError('Изменился состав термонаклеек: обновите характеристики через ozon_prepare_card --product thermo.')
    missing = []
    for key in ('category_id', 'type_id', 'price'):
        value = ozon.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            missing.append(key)
    for key in ('width_mm', 'height_mm', 'depth_mm', 'weight_g'):
        value = ozon.get('package', {}).get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            missing.append('package.' + key)
    if not product['colors']['main'].get('ozon_value'):
        missing.append('colors.main.ozon_value')
    if missing:
        raise PermanentError('Термонаклейки: заполните product.json перед выкладкой: ' + ', '.join(missing) + '. Категорию и справочники подготовьте через ozon_prepare_card --product thermo.')
