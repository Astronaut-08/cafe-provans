"""Розбір KML/KMZ із Google My Maps у контури зон доставки. Чисті функції, без БД.

Як це працює. Карта My Maps експортується в KML («⋮ → Експортувати в KML/KMZ»). Усередині
багатокутники (Placemark → Polygon) лежать у шарах (Folder), мають назву й колір заливки.
Для кожного багатокутника визначаємо зону доставки (green / yellow / red) у такому порядку:
  1. вручну (`--assign "Назва=green"`), якщо структура карти нестандартна;
  2. за назвою багатокутника («Зелена зона», «yellow»);
  3. за назвою шару;
  4. за кольором заливки (червоний, жовтий/помаранчевий, зелений).
Якщо кілька багатокутників належать одній зоні, вони зливаються в MultiPolygon.
Усе, що не багатокутник (мітки, лінії), ігнорується й потрапляє у звіт.
"""
import colorsys
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree as ET

from app.modules.delivery.geometry import validate_geometry

ZONE_CODES = ('green', 'yellow', 'red')
MAX_BYTES = 20 * 1024 * 1024  # KML із кількома зонами важить десятки кілобайтів; 20 МБ це вже підозріло

# \b у Python працює й для кирилиці. Латинське red без меж слова спрацювало б на «prepared».
_NAME_HINTS = {
    'green': re.compile(r'\b(зелен\w*|green)\b'),
    'yellow': re.compile(r'\b(жовт\w*|желт\w*|yellow)\b'),
    'red': re.compile(r'\b(червон\w*|красн\w*|red)\b'),
}


class KmlError(ValueError):
    """Файл не вдалося прочитати або він суперечить правилам. Текст призначений для людини."""


@dataclass
class KmlPolygon:
    name: str
    geometry: dict           # Polygon або MultiPolygon, [довгота, широта]
    color: str | None        # 'rrggbb' або None
    folder: str | None       # назва шару My Maps


@dataclass
class ParsedKml:
    polygons: list[KmlPolygon]
    ignored: list[str]       # назви обʼєктів, що не є багатокутниками


@dataclass
class Assignment:
    polygon: KmlPolygon
    code: str | None
    source: str              # 'вручну' / 'за назвою' / 'за шаром' / 'за кольором' / 'не визначено'


# ---------- читання файлу ----------

def read_kml_bytes(data: bytes) -> bytes:
    """Віддає XML-текст: звичайний KML як є, а з KMZ (zip) дістає doc.kml."""
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = [n for n in archive.namelist() if n.lower().endswith('.kml')]
                if not names:
                    raise KmlError('У KMZ-архіві немає .kml файлу')
                name = 'doc.kml' if 'doc.kml' in names else names[0]
                # розмір з заголовка архіву можна підробити, тому читаємо з обмеженням
                with archive.open(name) as handle:
                    data = handle.read(MAX_BYTES + 1)
        except zipfile.BadZipFile as exc:
            raise KmlError('Файл схожий на KMZ, але архів пошкоджений') from exc
    if len(data) > MAX_BYTES:
        raise KmlError('Файл завеликий для карти зон доставки')
    # Файл від користувача це недовірені дані: не приймаємо XML із DOCTYPE/ENTITY (атаки на розбір).
    # Експорт Google їх ніколи не містить.
    if re.search(rb'<!\s*(DOCTYPE|ENTITY)', data, re.IGNORECASE):
        raise KmlError('XML з оголошенням DOCTYPE/ENTITY не приймається')
    return data


def _local(element: ET.Element) -> str:
    return element.tag.rsplit('}', 1)[-1]


def _text(element: ET.Element, path: str) -> str:
    return (element.findtext(path) or '').strip()


# ---------- кольори ----------

def _kml_color_to_rgb(value: str | None) -> str | None:
    """KML зберігає колір як aabbggrr (так, навпаки до звичного rrggbb). Повертає 'rrggbb'."""
    if not value:
        return None
    value = value.strip().lower()
    if len(value) != 8 or any(ch not in '0123456789abcdef' for ch in value):
        return None
    return value[6:8] + value[4:6] + value[2:4]


def _style_color(style: ET.Element) -> str | None:
    for path in ('{*}PolyStyle/{*}color', '{*}LineStyle/{*}color'):
        color = _kml_color_to_rgb(style.findtext(path))
        if color:
            return color
    return None


def zone_from_color(rgb: str | None) -> str | None:
    """Найближча зона за відтінком. Сірі й дуже темні кольори не визначаються."""
    if not rgb:
        return None
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
    if saturation < 0.35 or value < 0.25:
        return None
    degrees = hue * 360
    if degrees < 20 or degrees >= 330:   # 330+: малиновий і рожево-червоний теж «червоні» для гостя
        return 'red'
    if degrees < 75:
        return 'yellow'      # жовтий і помаранчевий
    if degrees < 170:
        return 'green'
    return None              # блакитний, синій, фіолетовий: не наша палітра зон


def zone_from_name(name: str | None) -> str | None:
    """Зона за словом у назві. Якщо назва натякає одразу на кілька зон, вважаємо її невизначеною."""
    if not name:
        return None
    low = name.casefold()
    found = [code for code, pattern in _NAME_HINTS.items() if pattern.search(low)]
    return found[0] if len(found) == 1 else None


# ---------- розбір ----------

def _parse_ring(text: str | None, where: str) -> list[list[float]]:
    ring: list[list[float]] = []
    for token in (text or '').split():
        parts = token.split(',')
        try:
            if len(parts) < 2:
                raise ValueError
            ring.append([float(parts[0]), float(parts[1])])   # висоту (третє число) відкидаємо
        except ValueError:
            raise KmlError(f'{where}: некоректні координати {token!r}') from None
    if ring and ring[0] != ring[-1]:
        ring.append(list(ring[0]))   # KML вимагає замкнений контур; лагодимо замість відмови
    return ring


def _parse_polygon(polygon: ET.Element, where: str) -> list[list[list[float]]]:
    outer = polygon.find('{*}outerBoundaryIs/{*}LinearRing/{*}coordinates')
    if outer is None:
        raise KmlError(f'{where}: у багатокутнику немає зовнішнього контуру')
    rings = [_parse_ring(outer.text, where)]
    for inner in polygon.findall('{*}innerBoundaryIs/{*}LinearRing/{*}coordinates'):
        rings.append(_parse_ring(inner.text, where))
    return rings


def parse_kml(data: bytes) -> ParsedKml:
    xml = read_kml_bytes(data)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise KmlError(f'Не вдалося прочитати XML: {exc}') from exc
    if _local(root) != 'kml':
        raise KmlError('Це не KML (кореневий елемент має бути <kml>)')

    styles: dict[str, str | None] = {}
    style_maps: dict[str, str] = {}
    for element in root.iter():
        element_id = element.get('id')
        if not element_id:
            continue
        if _local(element) == 'Style':
            styles[element_id] = _style_color(element)
        elif _local(element) == 'StyleMap':
            for pair in element.findall('{*}Pair'):
                if _text(pair, '{*}key') == 'normal':
                    style_maps[element_id] = _text(pair, '{*}styleUrl').lstrip('#')

    def color_of(placemark: ET.Element) -> str | None:
        inline = placemark.find('{*}Style')
        if inline is not None and (color := _style_color(inline)):
            return color
        ref = _text(placemark, '{*}styleUrl').lstrip('#')
        ref = style_maps.get(ref, ref)   # StyleMap → її «normal» стиль
        return styles.get(ref)

    polygons: list[KmlPolygon] = []
    ignored: list[str] = []

    def walk(node: ET.Element, folder: str | None) -> None:
        for child in node:
            kind = _local(child)
            if kind in ('Document', 'Folder'):
                walk(child, _text(child, '{*}name') or folder)
            elif kind == 'Placemark':
                name = _text(child, '{*}name')
                # iterfind, а не iter: шаблон простору імен {*} підтримує лише XPath (find*), iter його ігнорує
                shapes = list(child.iterfind('.//{*}Polygon'))
                if not shapes:
                    ignored.append(name or '(без назви)')
                    continue
                where = f'«{name or "(без назви)"}»'
                parsed = [_parse_polygon(shape, where) for shape in shapes]
                geometry = (
                    {'type': 'Polygon', 'coordinates': parsed[0]} if len(parsed) == 1
                    else {'type': 'MultiPolygon', 'coordinates': parsed}
                )
                try:
                    validate_geometry(geometry)
                except ValueError as exc:
                    raise KmlError(f'{where}: {exc}') from exc
                polygons.append(KmlPolygon(name=name, geometry=geometry, color=color_of(child), folder=folder))

    walk(root, None)
    return ParsedKml(polygons=polygons, ignored=ignored)


# ---------- призначення зон ----------

def classify(polygons: list[KmlPolygon], overrides: dict[str, str] | None = None) -> list[Assignment]:
    overrides = {name.casefold(): code for name, code in (overrides or {}).items()}
    for name, code in overrides.items():
        if code not in ZONE_CODES:
            raise KmlError(f'--assign «{name}»: зона має бути одна з {", ".join(ZONE_CODES)}, а не «{code}»')
    known = {polygon.name.casefold() for polygon in polygons}
    unknown = sorted(name for name in overrides if name not in known)
    if unknown:
        raise KmlError(f'--assign: у файлі немає багатокутника з назвою {", ".join(f"«{n}»" for n in unknown)}')

    result: list[Assignment] = []
    for polygon in polygons:
        if (code := overrides.get(polygon.name.casefold())):
            result.append(Assignment(polygon, code, 'вручну'))
        elif (code := zone_from_name(polygon.name)):
            result.append(Assignment(polygon, code, 'за назвою'))
        elif (code := zone_from_name(polygon.folder)):
            result.append(Assignment(polygon, code, 'за шаром'))
        elif (code := zone_from_color(polygon.color)):
            result.append(Assignment(polygon, code, 'за кольором'))
        else:
            result.append(Assignment(polygon, None, 'не визначено'))
    return result


def build_zone_geometries(assignments: list[Assignment]) -> dict[str, dict]:
    """Збирає по одному контуру на зону. Відмовляє, якщо хоч один багатокутник лишився без зони."""
    unassigned = [a.polygon.name or '(без назви)' for a in assignments if a.code is None]
    if unassigned:
        names = ', '.join(f'«{n}»' for n in unassigned)
        raise KmlError(
            f'Не вдалося визначити зону для: {names}. Назвіть багатокутник на карті (наприклад «Зелена зона») '
            f'або вкажіть явно: --assign "Назва=green" (green, yellow або red).'
        )
    parts: dict[str, list] = {}
    for assignment in assignments:
        geometry = assignment.polygon.geometry
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        parts.setdefault(assignment.code, []).extend(polygons)
    return {
        code: ({'type': 'Polygon', 'coordinates': polys[0]} if len(polys) == 1
               else {'type': 'MultiPolygon', 'coordinates': polys})
        for code, polys in parts.items()
    }
