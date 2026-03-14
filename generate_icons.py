"""Generate PWA app icons as simple PNGs.

Creates a simple icon with "MTG" text on a dark background with accent color.
Requires no external dependencies — uses only the struct module to write
minimal valid PNG files.
"""

import struct
import zlib


def create_png(width: int, height: int) -> bytes:
    """Create a simple PNG icon with MTG branding colors."""
    bg = (26, 26, 46)       # #1a1a2e
    accent = (233, 69, 96)  # #e94560

    # Build pixel data: dark background with a colored border and center shape
    rows = []
    border = max(width // 16, 2)
    for y in range(height):
        row = []
        for x in range(width):
            # Border
            if x < border or x >= width - border or y < border or y >= height - border:
                row.extend(accent)
            # Inner pentagon/shield shape
            elif _in_shield(x, y, width, height):
                row.extend(accent)
            else:
                row.extend(bg)
        # PNG requires a filter byte at the start of each row
        rows.append(b'\x00' + bytes(row))

    raw_data = b''.join(rows)

    # Build PNG
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc

    signature = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)
    compressed = zlib.compress(raw_data)
    idat = chunk(b'IDAT', compressed)
    iend = chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


def _in_shield(x: int, y: int, w: int, h: int) -> bool:
    """Check if point is inside a shield/pentagon shape centered in the image."""
    cx, cy = w / 2, h / 2
    size = min(w, h) * 0.3

    # Simple diamond shape
    dx = abs(x - cx) / size
    dy = abs(y - cy) / size
    # Shift down slightly for shield look
    dy_shifted = (y - cy * 0.85) / size

    return dx + abs(dy_shifted) < 1.0 and dy < 1.2


if __name__ == '__main__':
    for size in [192, 512]:
        data = create_png(size, size)
        path = f'static/icon-{size}.png'
        with open(path, 'wb') as f:
            f.write(data)
        print(f'Created {path} ({len(data)} bytes)')
