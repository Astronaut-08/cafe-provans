"""Розбір KML/KMZ і призначення зон (чисті функції, без БД)."""
import pytest

from app.modules.delivery import kml as kml_module
from app.modules.delivery.geometry import geometry_contains
from app.modules.delivery.kml import (
    KmlError, build_zone_geometries, classify, parse_kml, zone_from_color, zone_from_name,
)
from tests.kml_samples import (
    GREEN_BOX, RED_BOX, YELLOW_BOX, folder, kml, kmz, placemark, polygon, style, three_zones_kml,
)


# ---------- розбір ----------

def test_parses_names_folders_and_geometry():
    parsed = parse_kml(three_zones_kml())
    assert [(p.name, p.folder, p.geometry['type']) for p in parsed.polygons] == [
        ('Зелена зона', 'Зелена', 'Polygon'), ('Жовта зона', 'Жовта', 'Polygon'), ('Червона зона', 'Червона', 'Polygon'),
    ]
    assert parsed.ignored == []


def test_coordinates_are_lng_lat_and_altitude_is_dropped():
    ring = parse_kml(three_zones_kml()).polygons[0].geometry['coordinates'][0]
    assert ring[0] == [23.84, 49.04]          # [довгота, широта], без третього числа
    assert ring[0] == ring[-1]
    assert all(len(point) == 2 for point in ring)


def test_color_is_resolved_through_stylemap_and_flipped_to_rgb():
    colors = [p.color for p in parse_kml(three_zones_kml()).polygons]
    # KML зберігає aabbggrr: наївне читання дало б '589d0f' (синій↔червоний навпаки)
    assert colors == ['0f9d58', 'f4b400', 'db4437']


def test_inline_style_wins_over_styleurl():
    inline = '<Style><PolyStyle><color>ff0000ff</color></PolyStyle></Style>'   # aabbggrr: червоний
    body = f'<Placemark><name>X</name>{inline}<styleUrl>#s</styleUrl>{polygon(*GREEN_BOX)}</Placemark>'
    parsed = parse_kml(kml(style('0F9D58', 's'), body))
    assert parsed.polygons[0].color == 'ff0000'


def test_polygon_without_style_has_no_color():
    assert parse_kml(kml(placemark('X', polygon(*GREEN_BOX)))).polygons[0].color is None


def test_hole_is_kept_as_second_ring():
    geometry = parse_kml(kml(placemark('X', polygon(*RED_BOX, hole=YELLOW_BOX)))).polygons[0].geometry
    assert len(geometry['coordinates']) == 2
    assert not geometry_contains(geometry, 23.85, 49.05)      # в отворі
    assert geometry_contains(geometry, 23.81, 49.01)          # між контуром і отвором


def test_multigeometry_becomes_multipolygon():
    multi = f'<MultiGeometry>{polygon(0, 0, 1, 1)}{polygon(5, 5, 6, 6)}</MultiGeometry>'
    geometry = parse_kml(kml(placemark('X', multi))).polygons[0].geometry
    assert geometry['type'] == 'MultiPolygon' and len(geometry['coordinates']) == 2


def test_non_polygons_are_ignored_and_reported():
    point = '<Point><coordinates>23.85,49.05,0</coordinates></Point>'
    line = '<LineString><coordinates>23.85,49.05,0 23.86,49.06,0</coordinates></LineString>'
    parsed = parse_kml(kml(placemark('Піцерія', point), placemark('Маршрут', line), placemark('Зона', polygon(*GREEN_BOX))))
    assert [p.name for p in parsed.polygons] == ['Зона']
    assert parsed.ignored == ['Піцерія', 'Маршрут']


def test_unclosed_ring_is_closed_automatically():
    parsed = parse_kml(kml(placemark('X', polygon(*GREEN_BOX, close=False))))
    ring = parsed.polygons[0].geometry['coordinates'][0]
    assert ring[0] == ring[-1] and len(ring) == 5


def test_nested_folders_use_the_nearest_folder_name():
    inner = folder('Внутрішній шар', placemark('X', polygon(*GREEN_BOX)))
    parsed = parse_kml(kml(folder('Зовнішній', inner)))
    assert parsed.polygons[0].folder == 'Внутрішній шар'


def test_kml_without_namespace_is_accepted():
    data = ('<kml><Document><Placemark><name>X</name><Polygon><outerBoundaryIs><LinearRing><coordinates>'
            '0,0 1,0 1,1 0,1 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>')
    assert len(parse_kml(data.encode()).polygons) == 1


def test_file_without_any_placemarks_gives_empty_result():
    parsed = parse_kml(kml())
    assert parsed.polygons == [] and parsed.ignored == []


# ---------- KMZ ----------

def test_kmz_is_unpacked():
    assert len(parse_kml(kmz(three_zones_kml())).polygons) == 3


def test_kmz_with_other_name_for_kml_is_found():
    assert len(parse_kml(kmz(three_zones_kml(), name='map.kml')).polygons) == 3


def test_kmz_without_kml_is_rejected():
    with pytest.raises(KmlError, match='немає .kml'):
        parse_kml(kmz(b'x', name='readme.txt'))


def test_broken_kmz_is_rejected():
    with pytest.raises(KmlError, match='пошкоджений'):
        parse_kml(b'PK\x03\x04 not really a zip')


# ---------- недовірений вхід ----------

@pytest.mark.parametrize('data, fragment', [
    (b'not xml at all', 'Не вдалося прочитати XML'),
    (b'<root/>', 'Це не KML'),
    (b'', 'Не вдалося прочитати XML'),
])
def test_garbage_is_rejected_with_clear_message(data, fragment):
    with pytest.raises(KmlError, match=fragment):
        parse_kml(data)


def test_doctype_and_entities_are_rejected():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
            b'<kml><Document><name>&b;</name></Document></kml>')
    with pytest.raises(KmlError, match='DOCTYPE'):
        parse_kml(bomb)


def test_oversized_file_is_rejected(monkeypatch):
    monkeypatch.setattr(kml_module, 'MAX_BYTES', 100)
    with pytest.raises(KmlError, match='завеликий'):
        parse_kml(three_zones_kml())


def test_oversized_kmz_content_is_rejected_even_if_archive_is_small(monkeypatch):
    monkeypatch.setattr(kml_module, 'MAX_BYTES', 100)
    with pytest.raises(KmlError, match='завеликий'):
        parse_kml(kmz(three_zones_kml()))


@pytest.mark.parametrize('coords, fragment', [
    ('abc,def', 'некоректні координати'),
    ('23.85', 'некоректні координати'),
    ('23.85,49.05 23.86,49.06', 'щонайменше'),                         # менше трьох вершин
    ('200,49,0 201,49,0 201,50,0 200,50,0 200,49,0', 'поза межами'),   # довгота > 180
])
def test_bad_coordinates_are_rejected_with_the_polygon_name(coords, fragment):
    body = (f'<Placemark><name>Погана</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}'
            f'</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>')
    with pytest.raises(KmlError, match=f'«Погана».*{fragment}'):
        parse_kml(kml(body))


def test_polygon_without_outer_boundary_is_rejected():
    with pytest.raises(KmlError, match='немає зовнішнього контуру'):
        parse_kml(kml('<Placemark><name>X</name><Polygon></Polygon></Placemark>'))


# ---------- визначення зони ----------

@pytest.mark.parametrize('rgb, expected', [
    ('0f9d58', 'green'), ('9ccc65', 'green'), ('00ff00', 'green'),
    ('f4b400', 'yellow'), ('ffea00', 'yellow'), ('f57c00', 'yellow'),   # жовтий і помаранчевий
    ('db4437', 'red'), ('ff0000', 'red'), ('c2185b', 'red'),
    ('4285f4', None), ('7b1fa2', None),     # синій, фіолетовий: не палітра зон
    ('757575', None), ('ffffff', None), ('000000', None), ('1a1a1a', None),   # сірі
    (None, None),
])
def test_zone_from_color(rgb, expected):
    assert zone_from_color(rgb) == expected


@pytest.mark.parametrize('name, expected', [
    ('Зелена зона', 'green'), ('ЗЕЛЕНА', 'green'), ('зелена', 'green'), ('Green', 'green'),
    ('Жовта зона', 'yellow'), ('Жовта', 'yellow'), ('Желтая', 'yellow'), ('yellow zone', 'yellow'),
    ('Червона зона', 'red'), ('червоний', 'red'), ('Красная', 'red'), ('Red', 'red'),
    ('Prepared', None),                 # «red» усередині слова не рахується
    ('Центр', None), ('', None), (None, None),
    ('зелена і червона', None),         # двозначна назва: краще не вгадувати
])
def test_zone_from_name(name, expected):
    assert zone_from_name(name) == expected


# ---------- призначення ----------

def classify_one(name='X', folder_name=None, color=None, overrides=None):
    from app.modules.delivery.kml import KmlPolygon
    poly = KmlPolygon(name=name, geometry={'type': 'Polygon', 'coordinates': []}, color=color, folder=folder_name)
    return classify([poly], overrides)[0]


def test_precedence_override_then_name_then_folder_then_color():
    assert classify_one('Жовта', 'Червона', '0f9d58', {'Жовта': 'red'}).code == 'red'          # вручну
    assert classify_one('Жовта', 'Червона', '0f9d58').code == 'yellow'                          # назва
    assert classify_one('Центр', 'Червона', '0f9d58').code == 'red'                             # шар
    assert classify_one('Центр', 'Шар', '0f9d58').code == 'green'                               # колір
    assert classify_one('Центр', 'Шар', None).code is None                                      # нічого


def test_source_of_each_decision_is_reported():
    assert [classify_one('Центр', None, '0f9d58').source, classify_one('Зелена').source,
            classify_one('Центр', 'Зелена').source, classify_one('Центр', overrides={'центр': 'red'}).source,
            classify_one('Центр').source] == ['за кольором', 'за назвою', 'за шаром', 'вручну', 'не визначено']


def test_override_matches_name_case_insensitively():
    assert classify_one('Центр', overrides={'ЦЕНТР': 'green'}).code == 'green'


def test_override_with_invalid_zone_is_rejected():
    with pytest.raises(KmlError, match='green, yellow, red'):
        classify_one('Центр', overrides={'Центр': 'blue'})


def test_override_for_missing_polygon_is_rejected_so_typos_are_not_silent():
    with pytest.raises(KmlError, match='немає багатокутника з назвою «центр»'):
        classify_one('Інший', overrides={'Центр': 'green'})


def test_full_map_is_classified_and_built():
    parsed = parse_kml(three_zones_kml())
    geometries = build_zone_geometries(classify(parsed.polygons))
    assert set(geometries) == {'green', 'yellow', 'red'}


def test_color_only_map_works_when_names_are_meaningless():
    body = [style('0F9D58'), style('DB4437'),
            placemark('Полігон 1', polygon(*GREEN_BOX), 'poly-0F9D58-1000-153-FF'),
            placemark('Полігон 2', polygon(*RED_BOX), 'poly-DB4437-1000-153-FF')]
    parsed = parse_kml(kml(*body))
    assert [a.code for a in classify(parsed.polygons)] == ['green', 'red']


def test_unassigned_polygon_blocks_build_and_explains_how_to_fix():
    parsed = parse_kml(kml(placemark('Центр', polygon(*GREEN_BOX)), placemark('Зелена', polygon(*RED_BOX))))
    with pytest.raises(KmlError) as error:
        build_zone_geometries(classify(parsed.polygons))
    message = str(error.value)
    assert '«Центр»' in message and '--assign' in message and '«Зелена»' not in message


def test_several_polygons_of_one_zone_are_merged_into_multipolygon():
    parsed = parse_kml(kml(
        placemark('Зелена 1', polygon(0, 0, 1, 1)),
        placemark('Зелена 2', polygon(5, 5, 6, 6)),
        placemark('Червона', polygon(20, 20, 30, 30)),
    ))
    zones = build_zone_geometries(classify(parsed.polygons))
    assert zones['green']['type'] == 'MultiPolygon' and len(zones['green']['coordinates']) == 2
    assert zones['red']['type'] == 'Polygon'
    assert geometry_contains(zones['green'], 5.5, 5.5) and geometry_contains(zones['green'], 0.5, 0.5)


def test_multipolygon_and_polygon_of_one_zone_are_flattened_together():
    multi = f'<MultiGeometry>{polygon(0, 0, 1, 1)}{polygon(5, 5, 6, 6)}</MultiGeometry>'
    parsed = parse_kml(kml(placemark('Зелена 1', multi), placemark('Зелена 2', polygon(10, 10, 11, 11))))
    green = build_zone_geometries(classify(parsed.polygons))['green']
    assert green['type'] == 'MultiPolygon' and len(green['coordinates']) == 3


# ---------- наскрізно: від KML до відповіді «в якій зоні точка» ----------

def test_end_to_end_points_land_in_the_right_zone_with_real_coordinates():
    zones = build_zone_geometries(classify(parse_kml(three_zones_kml()).polygons))

    def zone_for(lat, lng):
        # так само, як сервіс: від найближчої зони до найдальшої
        return next((c for c in ('green', 'yellow', 'red') if geometry_contains(zones[c], lng, lat)), None)

    assert zone_for(lat=49.05, lng=23.85) == 'green'
    assert zone_for(lat=49.035, lng=23.85) == 'yellow'
    assert zone_for(lat=49.01, lng=23.85) == 'red'
    assert zone_for(lat=50.00, lng=24.00) is None
    # переплутані широта й довгота дали б «поза зонами»: захист від класичної помилки
    assert zone_for(lat=23.85, lng=49.05) is None


# ---------- розкладка РЕАЛЬНИХ карт власника (прочитано з їхнього KML-експорту) ----------
# Карти малюють різні люди й різними способами, тому саме ці розкладки мають працювати без --assign:
#   «Болехів»: шар «Болехів», зони Зелена/Жовта/Червона, а червона це MultiGeometry із трьох контурів;
#   «Велика Тур'я»: шар «Зони доставки», жовта це MultiGeometry із трьох контурів, а червона складається
#   з ДВОХ окремих позначок: «Червона зона 1» і «Червона зона 2».
# Кольори Google My Maps: зелений #0F9D58, жовтий #FFEA00, червоний #A52714 (темний).

def _multi(*boxes) -> str:
    return f'<MultiGeometry>{"".join(polygon(*box) for box in boxes)}</MultiGeometry>'


def _real_styles() -> str:
    return style('0F9D58') + style('FFEA00') + style('A52714')


def test_real_layout_of_the_first_map_bolekhiv():
    parsed = parse_kml(kml(
        _real_styles(),
        folder(
            'Болехів',
            placemark('Зелена зона', polygon(23.85, 49.08, 23.87, 49.10), 'poly-0F9D58-1000-153-FF'),
            placemark('Жовта зона', polygon(23.88, 49.07, 23.91, 49.09), 'poly-FFEA00-1000-153-FF'),
            placemark('Червона зона', _multi((23.84, 49.04, 23.85, 49.05), (23.82, 49.05, 23.83, 49.06),
                                             (23.86, 49.03, 23.88, 49.05)), 'poly-A52714-1000-153-FF'),
        ),
    ))
    assignments = classify(parsed.polygons)
    zones = build_zone_geometries(assignments)

    assert {a.polygon.name: (a.code, a.source) for a in assignments} == {
        'Зелена зона': ('green', 'за назвою'), 'Жовта зона': ('yellow', 'за назвою'),
        'Червона зона': ('red', 'за назвою'),
    }
    assert zones['green']['type'] == 'Polygon' and zones['yellow']['type'] == 'Polygon'
    assert zones['red']['type'] == 'MultiPolygon' and len(zones['red']['coordinates']) == 3
    for lng, lat in [(23.845, 49.045), (23.825, 49.055), (23.87, 49.04)]:   # по точці в кожному з трьох контурів
        assert geometry_contains(zones['red'], lng, lat)


def test_real_layout_of_the_second_map_velyka_turia_two_red_placemarks():
    parsed = parse_kml(kml(
        _real_styles(),
        folder(
            'Зони доставки',
            placemark('Зелена зона', polygon(24.06, 49.14, 24.08, 49.15), 'poly-0F9D58-1000-153-FF'),
            placemark('Жовта зона', _multi((24.05, 49.11, 24.06, 49.12), (24.03, 49.12, 24.04, 49.13),
                                           (24.07, 49.10, 24.09, 49.11)), 'poly-FFEA00-1000-153-FF'),
            placemark('Червона зона 1', polygon(24.03, 49.15, 24.04, 49.16), 'poly-A52714-1000-153-FF'),
            placemark('Червона зона 2', polygon(24.00, 49.05, 24.01, 49.06), 'poly-A52714-1000-153-FF'),
        ),
    ))
    zones = build_zone_geometries(classify(parsed.polygons))

    assert set(zones) == {'green', 'yellow', 'red'}
    assert zones['green']['type'] == 'Polygon'
    assert zones['yellow']['type'] == 'MultiPolygon' and len(zones['yellow']['coordinates']) == 3
    # дві окремі позначки «Червона зона N» зливаються в ОДНУ зону red, а не затирають одна одну
    assert zones['red']['type'] == 'MultiPolygon' and len(zones['red']['coordinates']) == 2
    assert geometry_contains(zones['red'], 24.035, 49.155) and geometry_contains(zones['red'], 24.005, 49.055)


def test_google_colours_alone_are_enough_when_names_say_nothing():
    # запасний варіант: якщо на карті названо «Зона 1/2/3», зону визначає колір заливки
    parsed = parse_kml(kml(
        _real_styles(),
        placemark('Зона 1', polygon(0, 0, 1, 1), 'poly-0F9D58-1000-153-FF'),
        placemark('Зона 2', polygon(2, 2, 3, 3), 'poly-FFEA00-1000-153-FF'),
        placemark('Зона 3', polygon(4, 4, 5, 5), 'poly-A52714-1000-153-FF'),   # темний червоний
    ))
    assert [(a.code, a.source) for a in classify(parsed.polygons)] == [
        ('green', 'за кольором'), ('yellow', 'за кольором'), ('red', 'за кольором'),
    ]
