"""WB Studio: T-shirt cards for Wildberries generated from popular WB products.

Layers: config -> domain -> infrastructure -> application -> api.
"""

from PIL import PngImagePlugin

# Seller photos sometimes carry megabytes of PNG text metadata; only their pixels are used.
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024 * 1024
