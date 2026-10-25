"""Lazy product registry: importing one product does not load other product modules."""
from collections.abc import Mapping
from importlib import import_module
from printflow.products.base import Product

class ProductRegistry(Mapping):
    modules = {'shopper':'printflow.products.shopper.product:Shopper',
               'mousepad':'printflow.products.mousepad.product:Mousepad',
               'thermo':'printflow.products.thermo.product:Thermo'}

    def __iter__(self):
        return iter(self.modules)

    def __len__(self):
        return len(self.modules)

    def __getitem__(self, name):
        module, cls = self.modules[name].split(':')
        return getattr(import_module(module), cls)

PRODUCTS = ProductRegistry()

def get_product(name: str) -> Product:
    try:
        cls = PRODUCTS[name]
    except KeyError:
        raise SystemExit(f"Неизвестный товар «{name}». Есть: {', '.join(PRODUCTS)}") from None
    return cls()
