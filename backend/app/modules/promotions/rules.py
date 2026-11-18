from datetime import date, datetime, time, timedelta

from app.core.timewindow import in_time_window


def promotion_is_current(
    *,
    start_date: date | None,
    end_date: date | None,
    start_time: time | None,
    end_time: time | None,
    local_now: datetime,
) -> bool:
    """Чи діє акція в цей момент. `local_now` це місцевий час закладу (дати й години акції
    задані за ним). NULL означає «без обмеження». Статус (active) перевіряється окремо, в запиті.

    Нічна акція (end_time < start_time, наприклад 22:00 до 02:00): ранкова частина (00:00 до 02:00)
    належить вечору ПОПЕРЕДНЬОЇ доби. Тому дати (start_date/end_date) для неї перевіряємо за тією
    добою, у яку вікно почалося: акція «до 31 грудня 22:00-02:00» діє ще й 1 січня о 01:00.
    """
    current_time = local_now.time()
    if not in_time_window(start_time, end_time, current_time):
        return False

    business_date = local_now.date()
    overnight = start_time is not None and end_time is not None and end_time < start_time
    if overnight and current_time < end_time:
        business_date -= timedelta(days=1)

    if start_date is not None and business_date < start_date:
        return False
    if end_date is not None and business_date > end_date:
        return False
    return True
