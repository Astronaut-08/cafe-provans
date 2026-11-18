"""Геометрія зон доставки: чисті функції, без БД."""
import pytest

from app.modules.delivery.geometry import geometry_contains, validate_geometry
from tests.factories import square

OUTER = square(0, 0, 10, 10)


def with_hole() -> dict:
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    return {'type': 'Polygon', 'coordinates': [OUTER['coordinates'][0], hole]}


# ---------- «чи містить» ----------

@pytest.mark.parametrize('lng, lat, expected', [
    (5, 5, True),
    (0.1, 0.1, True),
    (9.9, 9.9, True),
    (-1, 5, False),
    (11, 5, False),
    (5, -1, False),
    (5, 11, False),
])
def test_square(lng, lat, expected):
    assert geometry_contains(OUTER, lng, lat) is expected


def test_longitude_and_latitude_are_not_swapped():
    # прямокутник витягнутий уздовж довготи: перестановка осей дала б іншу відповідь
    wide = square(0, 0, 20, 2)
    assert geometry_contains(wide, lng=15, lat=1) is True
    assert geometry_contains(wide, lng=1, lat=15) is False


def test_point_in_hole_is_outside():
    poly = with_hole()
    assert geometry_contains(poly, 5, 5) is False   # в отворі
    assert geometry_contains(poly, 2, 2) is True    # між контуром і отвором


def test_concave_polygon():
    # літера «Г»: опукла оболонка накрила б «порожній» кут
    ell = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10], [0, 0]]]}
    assert geometry_contains(ell, 1, 8) is True
    assert geometry_contains(ell, 8, 1) is True
    assert geometry_contains(ell, 8, 8) is False


def test_ray_through_a_vertex_is_counted_once():
    # ромб: горизонталь y=5 проходить рівно через дві вершини, (0,5) і (10,5). Наївний підрахунок
    # зарахував би вершину двічі (обидва ребра) і дав би хибну парність.
    diamond = {'type': 'Polygon', 'coordinates': [[[5, 0], [10, 5], [5, 10], [0, 5], [5, 0]]]}
    assert geometry_contains(diamond, 5, 5) is True
    assert geometry_contains(diamond, 3, 5) is True
    assert geometry_contains(diamond, 8, 5) is True
    assert geometry_contains(diamond, -1, 5) is False
    assert geometry_contains(diamond, 11, 5) is False
    # промінь через нижню й верхню вершини
    assert geometry_contains(diamond, 5, 0.5) is True
    assert geometry_contains(diamond, 1, 0) is False
    assert geometry_contains(diamond, 1, 10) is False


def test_slanted_edges_use_real_intersection_not_bounding_box():
    # трикутник: у правому верхньому куті його охоплюючого прямокутника точки вже ззовні
    triangle = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [0, 10], [0, 0]]]}
    assert geometry_contains(triangle, 2, 2) is True
    assert geometry_contains(triangle, 4.9, 4.9) is True
    assert geometry_contains(triangle, 5.1, 5.1) is False
    assert geometry_contains(triangle, 9, 9) is False


def test_multipolygon_matches_any_part():
    multi = {'type': 'MultiPolygon', 'coordinates': [
        square(0, 0, 1, 1)['coordinates'], square(10, 10, 11, 11)['coordinates'],
    ]}
    assert geometry_contains(multi, 0.5, 0.5) is True
    assert geometry_contains(multi, 10.5, 10.5) is True
    assert geometry_contains(multi, 5, 5) is False


def test_unknown_geometry_type_contains_nothing():
    assert geometry_contains({'type': 'Point', 'coordinates': [5, 5]}, 5, 5) is False


def test_third_coordinate_altitude_is_ignored():
    # KML віддає «lng,lat,alt»; висота не повинна впливати
    poly = {'type': 'Polygon', 'coordinates': [[[0, 0, 100], [10, 0, 100], [10, 10, 100], [0, 10, 100], [0, 0, 100]]]}
    assert geometry_contains(poly, 5, 5) is True


# ---------- валідація ----------

def test_valid_geometries_pass_and_are_returned_as_is():
    assert validate_geometry(OUTER) is OUTER
    multi = {'type': 'MultiPolygon', 'coordinates': [OUTER['coordinates']]}
    assert validate_geometry(multi) is multi
    poly = with_hole()
    assert validate_geometry(poly) is poly


@pytest.mark.parametrize('bad, fragment', [
    ('not a dict', 'обʼєктом'),
    ({'type': 'Point', 'coordinates': [1, 2]}, 'Polygon і MultiPolygon'),
    ({'type': 'Polygon'}, 'немає контурів'),
    ({'type': 'Polygon', 'coordinates': []}, 'немає контурів'),
    ({'type': 'MultiPolygon'}, 'порожня'),
    ({'type': 'MultiPolygon', 'coordinates': []}, 'порожня'),
    ({'type': 'Polygon', 'coordinates': [[]]}, 'щонайменше'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [0, 0]]]}, 'щонайменше'),          # лише 3 точки
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1]]]}, 'не замкнений'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], ['x', 1], [0, 0]]]}, 'некоректна точка'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [True, 1], [0, 0]]]}, 'некоректна точка'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1], [1, 1], [0, 1], [0, 0]]]}, 'некоректна точка'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 95], [0, 0]]]}, 'поза межами'),
    ({'type': 'Polygon', 'coordinates': [[[0, 0], [190, 0], [1, 1], [0, 1], [0, 0]]]}, 'поза межами'),
    ({'type': 'MultiPolygon', 'coordinates': [[]]}, 'немає контурів'),
])
def test_invalid_geometries_are_rejected_with_clear_message(bad, fragment):
    with pytest.raises(ValueError, match=fragment):
        validate_geometry(bad)


def test_error_message_points_to_the_broken_ring():
    broken_hole = [[4, 4], [6, 4], [6, 6], [4, 6]]  # не замкнений
    poly = {'type': 'Polygon', 'coordinates': [OUTER['coordinates'][0], broken_hole]}
    with pytest.raises(ValueError, match='багатокутник 1, контур 2'):
        validate_geometry(poly)
