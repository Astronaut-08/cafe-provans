"""Замовлення для персоналу. Усе під входом; роль і заклад перевіряють залежності й сервіс."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime

from app.core.params import IdPath
from app.db.enums import FulfillmentType, OrderStatus, PaymentStatus, UserRole
from app.db.models.user import User
from app.dependencies import get_current_user, get_now, require_roles
from app.modules.orders.schemas import OrderCreate, OrderListItem, OrderNotesUpdate, OrderRead, StatusChange
from app.modules.orders.service import OrderFilters, OrderService, get_order_service

router = APIRouter(prefix='/orders', tags=['Orders (staff)'])

# Хто що може. Адмін проходить усюди (див. require_roles).
_waiter = Depends(require_roles(UserRole.waiter))
_kitchen_or_waiter = Depends(require_roles(UserRole.waiter, UserRole.chef))


@router.post(
    '', response_model=OrderRead, status_code=status.HTTP_201_CREATED, dependencies=[_waiter],
    summary='Прийняти замовлення (офіціант, адмін)',
)
async def create_order(
    data: OrderCreate,
    actor: User = Depends(get_current_user),
    now: datetime = Depends(get_now),
    service: OrderService = Depends(get_order_service),
):
    """Ціни, назви, суму й доставку рахує сервер. Самовивіз: без `delivery`. Доставка: `delivery` з містом, вулицею
    й будинком; зона визначається за адресою, а сума має бути не меншою за мінімум зони."""
    return await service.create(actor, data, now)


@router.get(
    '', response_model=list[OrderListItem], dependencies=[_kitchen_or_waiter],
    summary='Список замовлень (офіціант, кухар, адмін)',
)
async def list_orders(
    actor: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
    location_id: int | None = Query(None, ge=1, le=2_147_483_647, description='Лише для адміна: заклад (без нього всі)'),
    order_status: list[OrderStatus] | None = Query(None, alias='status', description='Один чи кілька статусів'),
    active: bool = Query(False, description='Лише незавершені (не completed і не cancelled): екран кухні'),
    fulfillment_type: FulfillmentType | None = None,
    payment_status: PaymentStatus | None = None,
    created_from: AwareDatetime | None = Query(None, description='Створені не раніше (ISO 8601 з часовим поясом)'),
    created_to: AwareDatetime | None = Query(None, description='Створені раніше за цей момент'),
    search: str | None = Query(None, max_length=50, description='Номер замовлення, імʼя або телефон гостя'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = OrderFilters(
        location_id=location_id, statuses=order_status, active_only=active, fulfillment_type=fulfillment_type,
        payment_status=payment_status, created_from=created_from, created_to=created_to, search=search,
        limit=limit, offset=offset,
    )
    return await service.list_orders(actor, filters)


@router.get(
    '/{order_id}', response_model=OrderRead, dependencies=[_kitchen_or_waiter], summary='Картка замовлення',
)
async def get_order(
    order_id: IdPath,
    actor: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return await service.get(actor, order_id)


@router.post(
    '/{order_id}/status', response_model=OrderRead, dependencies=[_kitchen_or_waiter],
    summary='Змінити статус замовлення',
)
async def change_status(
    order_id: IdPath,
    data: StatusChange,
    actor: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    """Офіціант і адмін роблять будь-який дозволений перехід, кухар лише «у роботі» і «готово».
    Дозволені наступні кроки для вас повертає сама картка в `allowed_statuses`."""
    return await service.change_status(actor, order_id, data.status, data.comment)


@router.post(
    '/{order_id}/payment/confirm', response_model=OrderRead, dependencies=[_waiter],
    summary='Відмітити, що гроші отримано (готівка чи термінал)',
)
async def confirm_payment(
    order_id: IdPath,
    actor: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return await service.confirm_payment(actor, order_id)


@router.patch(
    '/{order_id}', response_model=OrderRead, dependencies=[_waiter], summary='Нотатки персоналу до замовлення',
)
async def update_order_notes(
    order_id: IdPath,
    data: OrderNotesUpdate,
    actor: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return await service.update_notes(actor, order_id, data.staff_notes)
