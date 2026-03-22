"""
Image processing: blur, compression utilities.
"""
import io
from typing import Optional
from PIL import Image, ImageFilter


def blur_image(image_bytes: bytes, radius: int = 10) -> bytes:
    """Apply Gaussian blur to image. Returns JPEG bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    out = io.BytesIO()
    blurred.save(out, format="JPEG", quality=85)
    return out.getvalue()


def compress_image(image_bytes: bytes, max_size: int = 200 * 1024) -> bytes:
    """
    Compress image to target size (default 200KB).
    Returns JPEG bytes.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    
    quality = 85
    while quality > 20:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        data = out.getvalue()
        if len(data) <= max_size:
            return data
        quality -= 10
    
    # If still too large, also resize
    w, h = img.size
    while len(data) > max_size and w > 200:
        w = int(w * 0.8)
        h = int(h * 0.8)
        resized = img.resize((w, h), Image.LANCZOS)
        out = io.BytesIO()
        resized.save(out, format="JPEG", quality=60)
        data = out.getvalue()
    
    return data


def process_image_bytes(
    image_bytes: bytes,
    blur_radius: int = 0,
    compress: bool = False,
) -> bytes:
    """Apply blur and/or compression to image bytes."""
    result = image_bytes
    if blur_radius > 0:
        result = blur_image(result, radius=blur_radius)
    if compress:
        result = compress_image(result)
    return result
