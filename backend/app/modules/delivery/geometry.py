"""Геометрія зон доставки: GeoJSON Polygon / MultiPolygon, координати [довгота, широта].

Без зовнішніх бібліотек (shapely тощо): для визначення «в якій зоні точка» достатньо променевого
методу, а зони невеликі. Точка рівно на межі може потрапити всередину або назовні (для
координат із двома-трьома десятковими знаками вулиці це неможливо відрізнити від похибки GPS).
"""
from typing import Any

Position = list[float]   # [lng, lat]
Ring = list[Position]    # замкнений контур: перша точка = остання
MIN_RING_POSITIONS = 4   # три різні вершини + замикаюча


def _point_in_ring(lng: float, lat: float, ring: Ring) -> bool:
    """Променевий метод: рахуємо перетини променя вправо від точки з ребрами контуру."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        # ребро перетинає горизонталь точки, і точка лівіше за перетин
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygon_contains(rings: list[Ring], lng: float, lat: float) -> bool:
    """rings[0]: зовнішній контур, решта: отвори (точка в отворі не належить багатокутнику)."""
    if not rings or not _point_in_ring(lng, lat, rings[0]):
        return False
    return not any(_point_in_ring(lng, lat, hole) for hole in rings[1:])


def geometry_contains(geometry: dict[str, Any], lng: float, lat: float) -> bool:
    kind = geometry.get('type')
    coordinates = geometry.get('coordinates')
    if kind == 'Polygon':
        return _polygon_contains(coordinates, lng, lat)
    if kind == 'MultiPolygon':
        return any(_polygon_contains(polygon, lng, lat) for polygon in coordinates)
    return False


def _validate_ring(ring: Any, where: str) -> None:
    if not isinstance(ring, list) or len(ring) < MIN_RING_POSITIONS:
        raise ValueError(f'{where}: у контурі має бути щонайменше {MIN_RING_POSITIONS} точки')
    for position in ring:
        if not (isinstance(position, list) and len(position) >= 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in position[:2])):
            raise ValueError(f'{where}: некоректна точка {position!r}')
        lng, lat = position[0], position[1]
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError(f'{where}: координати поза межами ({lng}, {lat}); порядок має бути [довгота, широта]')
    if ring[0][:2] != ring[-1][:2]:
        raise ValueError(f'{where}: контур не замкнений (перша й остання точки різні)')


def validate_geometry(geometry: Any) -> dict[str, Any]:
    """Перевіряє, що це коректний Polygon або MultiPolygon; повертає його ж. ValueError з поясненням українською."""
    if not isinstance(geometry, dict):
        raise ValueError('геометрія має бути обʼєктом')
    kind = geometry.get('type')
    coordinates = geometry.get('coordinates')
    if kind == 'Polygon':
        polygons = [coordinates]
    elif kind == 'MultiPolygon':
        polygons = coordinates
    else:
        raise ValueError(f'підтримуються лише Polygon і MultiPolygon, а не {kind!r}')
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('порожня геометрія')
    for p, rings in enumerate(polygons):
        if not isinstance(rings, list) or not rings:
            raise ValueError(f'багатокутник {p + 1}: немає контурів')
        for r, ring in enumerate(rings):
            _validate_ring(ring, f'багатокутник {p + 1}, контур {r + 1}')
    return geometry
