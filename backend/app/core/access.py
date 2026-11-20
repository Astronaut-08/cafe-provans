"""Спільна перевірка: до якого закладу має доступ працівник.

Адмін працює з будь-яким закладом. Офіціант і кухар прив'язані до ОДНОГО закладу (`users.location_id`)
і можуть чіпати лише його дані: страви в стоп-листі, замовлення. Правило однакове скрізь, тому
живе в одному місці, а не копіюється в кожен сервіс.
"""
from app.core.exceptions import ForbiddenError
from app.db.enums import UserRole
from app.db.models.user import User


def ensure_location_access(actor: User, location_id: int, *, other_location_message: str) -> None:
    """403, якщо працівник не адмін і заклад не його (або його взагалі не прив'язано до закладу).

    `other_location_message` це текст для чужого закладу: він залежить від дії («лише страви свого
    закладу», «лише замовлення свого закладу»), код помилки один: `other_location`.
    """
    if actor.role is UserRole.admin:
        return
    if actor.location_id is None:
        raise ForbiddenError('Вас не прив\'язано до закладу, зверніться до адміністратора', code='no_location')
    if actor.location_id != location_id:
        raise ForbiddenError(other_location_message, code='other_location')
