"""Синтетичні KML у форматі, який віддає Google My Maps. Самі файли власника нам недоступні, але розкладку
його двох карт (назви, шари, кольори, MultiGeometry, дві «червоні» позначки) відтворено в test_kml.py:
test_real_layout_* і test_google_colours_*."""
import zipfile
from io import BytesIO

NS = 'http://www.opengis.net/kml/2.2'


def style(color_rgb: str, name: str | None = None) -> str:
    """Стиль + StyleMap, як в експорті My Maps. KML зберігає колір як aabbggrr, тому rgb перевертаємо."""
    r, g, b = color_rgb[0:2], color_rgb[2:4], color_rgb[4:6]
    sid = name or f'poly-{color_rgb.upper()}-1000-153-FF'
    return (
        f'<Style id="{sid}-normal"><LineStyle><color>ff{b}{g}{r}</color><width>1</width></LineStyle>'
        f'<PolyStyle><color>99{b}{g}{r}</color><fill>1</fill><outline>1</outline></PolyStyle></Style>'
        f'<StyleMap id="{sid}"><Pair><key>normal</key><styleUrl>#{sid}-normal</styleUrl></Pair>'
        f'<Pair><key>highlight</key><styleUrl>#{sid}-highlight</styleUrl></Pair></StyleMap>'
    )


def ring(west: float, south: float, east: float, north: float, *, close=True) -> str:
    """Контур у KML-порядку «довгота,широта,висота» через пробіл."""
    points = [(west, south), (east, south), (east, north), (west, north)]
    if close:
        points.append(points[0])
    return ' '.join(f'{lng},{lat},0' for lng, lat in points)


def polygon(west, south, east, north, *, hole: tuple | None = None, close=True) -> str:
    inner = ''
    if hole:
        inner = f'<innerBoundaryIs><LinearRing><coordinates>{ring(*hole)}</coordinates></LinearRing></innerBoundaryIs>'
    return (
        '<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing>'
        f'<coordinates>{ring(west, south, east, north, close=close)}</coordinates>'
        f'</LinearRing></outerBoundaryIs>{inner}</Polygon>'
    )


def placemark(name: str, geometry: str, style_id: str | None = None) -> str:
    style_ref = f'<styleUrl>#{style_id}</styleUrl>' if style_id else ''
    return f'<Placemark><name>{name}</name>{style_ref}{geometry}</Placemark>'


def folder(name: str, *placemarks: str) -> str:
    return f'<Folder><name>{name}</name>{"".join(placemarks)}</Folder>'


def kml(*body: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="{NS}"><Document><name>Зони</name>'
        f'{"".join(body)}</Document></kml>'
    ).encode('utf-8')


def kmz(kml_bytes: bytes, name='doc.kml') -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, kml_bytes)
    return buffer.getvalue()


# Болехів ≈ 49.05° пн.ш., 23.85° сх.д.; три вкладені прямокутники, як зони на карті
GREEN_BOX = (23.84, 49.04, 23.86, 49.06)
YELLOW_BOX = (23.83, 49.03, 23.87, 49.07)
RED_BOX = (23.80, 49.00, 23.90, 49.10)


def three_zones_kml() -> bytes:
    """Типова карта: три шари-зони з кольорами Google My Maps (зелений, жовтий, червоний)."""
    return kml(
        style('0F9D58'), style('F4B400'), style('DB4437'),
        folder('Зелена', placemark('Зелена зона', polygon(*GREEN_BOX), 'poly-0F9D58-1000-153-FF')),
        folder('Жовта', placemark('Жовта зона', polygon(*YELLOW_BOX), 'poly-F4B400-1000-153-FF')),
        folder('Червона', placemark('Червона зона', polygon(*RED_BOX), 'poly-DB4437-1000-153-FF')),
    )
