from datetime import UTC, datetime, time, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

log = structlog.get_logger('app.time')


def to_local(now: datetime, tz_name: str) -> datetime:
    """Переводить момент `now` (aware) у місцевий час закладу. Дати й години в БД (акції, графік)
    записані за місцевим часом закладу, а сервер працює в UTC.
    Некоректна назва пояса в БД не повинна валити публічне меню: пишемо попередження й беремо UTC.
    """
    zone: tzinfo
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning('invalid_timezone', timezone=tz_name)
        zone = UTC
    return now.astimezone(zone)


def in_time_window(start: time | None, end: time | None, current: time) -> bool:
    """Чи потрапляє `current` у щоденне вікно [start, end). Використовується для годин роботи
    закладу та для часу дії акцій.

    - обидва NULL: вікна немає, завжди True;
    - лише start: з цього часу до кінця доби; лише end: від початку доби до цього часу;
    - start == end: уся доба (00:00 до 00:00 означає «цілодобово», а не «ніколи»);
    - end < start: вікно через північ (22:00 до 02:00): True, якщо current >= start АБО current < end.
    Кінець не включається: о 02:00 нічна акція вже не діє.
    """
    if start is None and end is None:
        return True
    if start is None:
        return current < end
    if end is None:
        return current >= start
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end
