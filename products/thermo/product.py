"""Термонаклейки: один товар на дизайн, общий конвейер очереди и Ozon."""
from printflow.products.base import Product

class Thermo(Product):
    name = 'thermo'
    env_prefix = 'THERMO'
    title = 'Термонаклейки'
    main_slide = '01-cover'
    default_card_name = None
    names_designs = True
    picks_subjects = True
    ozon_type_name = 'Термонаклейка'

    def prepare_spec(self, spec):
        from dataclasses import replace
        # Production currently sells only the single A4 transfer.
        bound = self.for_spec(replace(spec, assortment="single", product_config=None))
        return replace(spec, assortment=bound.config['assortment']['mode'], product_config=bound.config)

    def for_spec(self, spec, snapshot=None):
        import copy
        from .domain.assortment import configure, sizes
        current = copy.deepcopy(self.config)
        mode = spec.assortment or current.get('assortment', {}).get('mode', 'set')
        config = copy.deepcopy(snapshot or spec.product_config) if snapshot or spec.product_config else configure(current, mode)
        if not (snapshot or spec.product_config):
            config['ozon'].update(copy.deepcopy(current.get('offers', {}).get(mode, {}).get('ozon', {})))
        selected = sizes(config)
        if len(selected) != (1 if config['assortment']['mode'] == 'single' else 3):
            raise ValueError('Рабочие комплектации thermo: один принт или набор ровно из трёх размеров')
        # Draft jobs can be prepared before marketplace category/price are configured.
        latest = copy.deepcopy(current['ozon'])
        latest.update(current.get('offers', {}).get(config['assortment']['mode'], {}).get('ozon', {}))
        for key in ('category_id', 'type_id', 'price'):
            if config['ozon'].get(key) is None:
                config['ozon'][key] = latest.get(key)
        for key,value in latest.get('package', {}).items():
            if config['ozon'].get('package', {}).get(key) is None:
                config['ozon'].setdefault('package', {})[key] = value
        if not config['ozon'].get('attributes'):
            config['ozon']['attributes'] = latest.get('attributes', [])
            if 'prepared_assortment_count' in latest:
                config['ozon']['prepared_assortment_count'] = latest['prepared_assortment_count']
        for key,value in current['colors'].items():
            if not config['colors'][key].get('ozon_value'):
                config['colors'][key]['ozon_value'] = copy.deepcopy(value.get('ozon_value', []))
        config['generation']['print_area_cm'] = list(selected[0]['size_cm'])
        bound = type(self)()
        bound._config = config
        return bound

    @property
    def config(self):
        from .domain.assortment import listing_config
        config = super().config
        config['ozon'] = listing_config(config)['ozon']
        return config

    def validate_publication(self):
        from .infrastructure.ozon_listing import validate_publication
        validate_publication(self.config)

    def resolve_print(self, png):
        import io
        from .domain.assortment import resolve_artwork
        from .infrastructure.gallery.geometry import load_print
        art = load_print(io.BytesIO(png))
        if not art.getchannel('A').getbbox():
            raise ValueError('Empty thermo print')
        self._config = resolve_artwork(self.config, art.size)
        return self.config

    def variants(self, spec):
        return ['main']

    def generator(self, openai):
        import copy
        from .domain.assortment import sizes
        from .infrastructure.print_generator import ThermoPrintGenerator
        generation = copy.deepcopy(self.config['generation'])
        items = sizes(self.config)
        if len(items) == 1:
            generation['print_area_cm'] = list(items[0]['size_cm'])
        return ThermoPrintGenerator(openai, generation)

    def gallery(self):
        from .infrastructure.gallery.renderer import ThermoGalleryRenderer
        return ThermoGalleryRenderer(self.config, self.templates_dir)

    def build_items(self, article, images, product_name, group, design=None):
        from .infrastructure.ozon_listing import build_items
        return build_items(article, images['main'], self.config, product_name, group, design)
