"""Сервіс замовлень: створення, список, картка, зміна статусу, оплата на місці.

Усе, що пише в БД, робиться в ОДНІЙ транзакції (один commit у кінці методу): замовлення, його позиції,
платіж і перший запис історії або з'являються разом, або не з'являється нічого.

Звідки береться кожне число (клієнт їх не надсилає, лише що замовлено й скільки):
- ціна страви: `dishes.price`, а якщо в закладі є власна, то `dish_locations.price_override`;
- ціна акції: те, що показує GET /locations/{id}/promotions (власна ціна акції або сума позицій);
- доставка: безкоштовна, але лише якщо сума не менша за мінімум зони (400 / 600 / 1000);
- підсумок: сума позицій + доставка, а БД ще й сама перевіряє `total = subtotal + delivery`.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog
from fastapi import Depends
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ensure_location_access
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.db.enums import FulfillmentType, OrderSource, OrderStatus, PaymentStatus, UserRole
from app.db.models.customer import Customer
from app.db.models.delivery_zone import DeliveryZone
from app.db.models.dish import Dish
from app.db.models.dish_location import DishLocation
from app.db.models.location import Location
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.order_status_history import OrderStatusHistory
from app.db.models.payment import Payment
from app.db.models.user import User
from app.dependencies import get_db
from app.modules.delivery.service import DeliveryService
from app.modules.locations.service import LocationService
from app.modules.menu.pricing import effective_price, is_dish_available
from app.modules.orders.schemas import (
    CustomerRead, DeliveryAddress, OrderCreate, OrderItemCreate, OrderItemRead, OrderListItem, OrderRead,
    PaymentRead, StaffBrief, StatusHistoryRead, ZoneRead,
)
from app.modules.orders.transitions import (
    ACTIVE_STATUSES, allowed_for, next_statuses, role_may,
)
from app.modules.payments.rules import summarize_payments
from app.modules.promotions.service import PromotionService

log = structlog.get_logger('app.orders')

# Стеля суми замовлення. Не бізнес-правило, а захист від одруківки й від переповнення Numeric(10, 2).
MAX_ORDER_TOTAL = Decimal('1000000')

_DELIVERY_MESSAGES = {
    'outside_zones': 'За цією адресою доставки немає, лише самовивіз',
    'not_configured': 'Для цього закладу доставку ще не налаштовано',
    'street_required': 'Вкажіть вулицю',
    'ambiguous_street': 'Уточніть тип вулиці (вул., пров., просп.): такі назви є в різних зонах',
}


@dataclass
class _Line:
    """Позиція з уже порахованою ціною (знімок на момент замовлення)."""
    dish_id: int | None
    promotion_id: int | None
    name: str
    unit_price: Decimal
    quantity: int
    note: str | None


@dataclass
class OrderFilters:
    location_id: int | None = None
    statuses: list[OrderStatus] | None = None
    active_only: bool = False
    fulfillment_type: FulfillmentType | None = None
    payment_status: PaymentStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    search: str | None = None
    limit: int = 50
    offset: int = 0


def _like_pattern(term: str) -> str:
    """Підрядок для LIKE: службові символи % і _ у пошуковому слові шукаються як звичайні."""
    escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- створення ----------

    async def create(self, actor: User, data: OrderCreate, now: datetime) -> OrderRead:
        """Приймає замовлення від персоналу (офіціант вносить із телефону чи з залу; адмін будь-де)."""
        ensure_location_access(
            actor, data.location_id, other_location_message='Можна приймати замовлення лише свого закладу',
        )
        location = await LocationService(self.session).get_active(data.location_id)

        lines = await self._price_lines(location, data.items, now)
        subtotal = sum((line.unit_price * line.quantity for line in lines), Decimal('0'))
        if subtotal <= 0:
            raise UnprocessableError('Сума замовлення має бути більшою за нуль', code='order_total_zero')
        if subtotal > MAX_ORDER_TOTAL:
            raise UnprocessableError('Сума замовлення завелика, перевірте кількість', code='order_too_large')

        zone_id: int | None = None
        delivery_price = Decimal('0')
        address: str | None = None
        if data.fulfillment_type is FulfillmentType.delivery:
            assert data.delivery is not None  # гарантує схема OrderCreate
            zone_id, delivery_price = await self._check_delivery(location.id, data.delivery, subtotal)
            address = data.delivery.as_text()

        customer = await self._upsert_customer(data.customer.phone, data.customer.full_name)
        total = subtotal + delivery_price

        order = Order(
            # справжній номер залежить від id, якого ще немає; тимчасовий унікальний замінимо одразу після flush
            order_number=f'new-{uuid.uuid4().hex[:20]}',
            location_id=location.id, customer_id=customer.id,
            source=OrderSource.waiter, fulfillment_type=data.fulfillment_type,
            delivery_zone_id=zone_id, delivery_address=address,
            payment_status=PaymentStatus.pending,   # спосіб оплати вибрано, гроші візьмемо на місці
            subtotal_price=subtotal, delivery_price=delivery_price, total_price=total,
            staff_notes=data.staff_notes,
        )
        self.session.add(order)
        await self.session.flush()
        order_id = order.id
        order.order_number = f'PR-{order_id:06d}'

        for line in lines:
            self.session.add(OrderItem(
                order_id=order_id, dish_id=line.dish_id, promotion_id=line.promotion_id,
                name=line.name, unit_price=line.unit_price, quantity=line.quantity, note=line.note,
            ))
        self.session.add(OrderStatusHistory(order_id=order_id, status=OrderStatus.new, changed_by=actor.id))
        self.session.add(Payment(
            order_id=order_id, provider=data.payment_method.value, amount=total, status=PaymentStatus.pending,
        ))
        await self.session.commit()

        log.info(
            'order_created', order_id=order_id, order_number=f'PR-{order_id:06d}', location_id=location.id,
            fulfillment=data.fulfillment_type.value, total=str(total), by=actor.id,
        )
        return await self._read(order_id, actor)

    async def _price_lines(
        self, location: Location, items: list[OrderItemCreate], now: datetime,
    ) -> list[_Line]:
        """Перетворює «що замовили» на позиції з цінами закладу. Усі проблеми збираємо РАЗОМ і віддаємо
        одним списком, щоб офіціант виправив усе за раз, а не по одній помилці за спробу."""
        dish_ids = {item.dish_id for item in items if item.dish_id is not None}
        dishes = {}
        if dish_ids:
            rows = await self.session.execute(
                select(
                    Dish.id, Dish.name, Dish.price,
                    Dish.is_available.label('dish_available'),
                    DishLocation.is_available.label('location_available'),
                    DishLocation.price_override,
                )
                .outerjoin(DishLocation, and_(DishLocation.dish_id == Dish.id, DishLocation.location_id == location.id))
                .where(Dish.id.in_(dish_ids))
            )
            dishes = {row.id: row for row in rows}

        promotions = {}
        if any(item.promotion_id is not None for item in items):
            # те саме, що бачить гість: акція діє в закладі просто зараз (статус, дати, години, привʼязка до закладу)
            promotions = {p.id: p for p in await PromotionService(self.session).list_active(location, now)}

        lines: list[_Line] = []
        problems: list[dict] = []
        for item in items:
            if item.dish_id is not None:
                row = dishes.get(item.dish_id)
                if row is None:
                    problems.append({'dish_id': item.dish_id, 'name': None, 'reason': 'not_found'})
                elif row.location_available is None:
                    problems.append({'dish_id': item.dish_id, 'name': row.name, 'reason': 'not_in_menu'})
                elif not is_dish_available(row.dish_available, row.location_available):
                    problems.append({'dish_id': item.dish_id, 'name': row.name, 'reason': 'unavailable'})
                else:
                    lines.append(_Line(
                        dish_id=row.id, promotion_id=None, name=row.name,
                        unit_price=effective_price(row.price, row.price_override),
                        quantity=item.quantity, note=item.note,
                    ))
            else:
                promo = promotions.get(item.promotion_id)
                if promo is None:
                    # не діє зараз, не в цьому закладі або не існує: гостю й персоналу це одне й те саме
                    problems.append({'promotion_id': item.promotion_id, 'name': None, 'reason': 'unavailable'})
                elif promo.has_unavailable_items:
                    problems.append({'promotion_id': item.promotion_id, 'name': promo.title, 'reason': 'unavailable'})
                else:
                    lines.append(_Line(
                        dish_id=None, promotion_id=promo.id, name=promo.title[:200],
                        unit_price=promo.price, quantity=item.quantity, note=item.note,
                    ))

        if problems:
            raise UnprocessableError(
                'Деяких позицій немає в наявності або в меню цього закладу', code='invalid_items', details=problems,
            )
        return lines

    async def _check_delivery(self, location_id: int, address: DeliveryAddress, subtotal: Decimal) -> tuple[int, Decimal]:
        """Зона за містом і вулицею та перевірка мінімальної суми. Повертає (id зони, ціна доставки)."""
        check = await DeliveryService(self.session).check_address(location_id, address.city, address.street)
        if not check.deliverable:
            raise UnprocessableError(
                _DELIVERY_MESSAGES[check.reason], code='delivery_unavailable', details={'reason': check.reason},
            )
        minimum = check.zone.min_order_amount
        if subtotal < minimum:
            raise UnprocessableError(
                f'Мінімальна сума замовлення з доставкою в цю зону: {minimum:.0f} грн',
                code='below_minimum_order',
                details={'zone': check.zone.code, 'min_order_amount': float(minimum), 'subtotal': float(subtotal)},
            )
        return check.zone_id, check.delivery_price

    async def _upsert_customer(self, phone: str, full_name: str | None) -> Customer:
        """Гість за телефоном: є, то беремо, немає, то створюємо. Одним запитом (INSERT ... ON CONFLICT),
        тому два замовлення з одним номером одночасно не розіб'ються на дублі й не впадуть на унікальності.
        Імʼя лише ДОПИСУЄМО, якщо його не було; уже збережене не перезаписуємо (одруківка в наступному замовленні)."""
        statement = insert(Customer).values(phone=phone, full_name=full_name)
        statement = statement.on_conflict_do_update(
            index_elements=['phone'],
            set_={'full_name': func.coalesce(Customer.__table__.c.full_name, statement.excluded.full_name)},
        ).returning(Customer)
        result = await self.session.execute(statement, execution_options={'populate_existing': True})
        return result.scalar_one()

    # ---------- читання ----------

    async def get(self, actor: User, order_id: int) -> OrderRead:
        order = await self._load(order_id)
        ensure_location_access(actor, order.location_id, other_location_message='Це замовлення іншого закладу')
        return await self._read(order_id, actor)

    async def list_orders(self, actor: User, filters: OrderFilters) -> list[OrderListItem]:
        """Список для екрана замовлень: найновіші першими. Офіціант і кухар бачать лише свій заклад,
        адмін усі (або один, якщо передано location_id)."""
        if actor.role is UserRole.admin:
            scope = filters.location_id
        else:
            ensure_location_access(
                actor, filters.location_id if filters.location_id is not None else actor.location_id,
                other_location_message='Можна дивитися замовлення лише свого закладу',
            )
            scope = actor.location_id

        items_count = (
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .where(OrderItem.order_id == Order.id)
            .correlate(Order)
            .scalar_subquery()
        )
        statement = (
            select(
                Order.id, Order.order_number, Order.location_id, Order.source, Order.fulfillment_type,
                Order.status, Order.payment_status, Order.delivery_address, Order.total_price, Order.created_at,
                Customer.full_name.label('customer_name'), Customer.phone.label('customer_phone'),
                items_count.label('items_count'),
            )
            .join(Customer, Customer.id == Order.customer_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(filters.limit).offset(filters.offset)
        )
        if scope is not None:
            statement = statement.where(Order.location_id == scope)
        if filters.statuses:
            statement = statement.where(Order.status.in_(filters.statuses))
        if filters.active_only:
            statement = statement.where(Order.status.in_(ACTIVE_STATUSES))
        if filters.fulfillment_type is not None:
            statement = statement.where(Order.fulfillment_type == filters.fulfillment_type)
        if filters.payment_status is not None:
            statement = statement.where(Order.payment_status == filters.payment_status)
        if filters.created_from is not None:
            statement = statement.where(Order.created_at >= filters.created_from)
        if filters.created_to is not None:
            statement = statement.where(Order.created_at < filters.created_to)
        if filters.search and filters.search.strip():
            term = filters.search.strip()
            # телефон шукаємо без пробілів і дужок: «067 123» знайде +380671234567
            phone_term = re.sub(r'[\s\-().]', '', term)
            conditions = [
                Order.order_number.ilike(_like_pattern(term), escape='\\'),
                Customer.full_name.ilike(_like_pattern(term), escape='\\'),
            ]
            if phone_term:
                conditions.append(Customer.phone.ilike(_like_pattern(phone_term), escape='\\'))
            statement = statement.where(or_(*conditions))

        rows = (await self.session.execute(statement)).all()
        return [OrderListItem.model_validate(row, from_attributes=True) for row in rows]

    # ---------- зміна статусу ----------

    async def change_status(
        self, actor: User, order_id: int, target: OrderStatus, comment: str | None,
    ) -> OrderRead:
        """Переводить замовлення в наступний статус, якщо це дозволено шляхом замовлення І роллю працівника.

        Рядок замовлення блокуємо (`FOR UPDATE`): якщо двоє одночасно натиснули кнопку, друга зміна чекає,
        бачить уже новий статус і чесно отримує 409, а не тихо перезаписує першу.
        """
        order = await self._load(order_id, lock=True)
        ensure_location_access(actor, order.location_id, other_location_message='Це замовлення іншого закладу')

        allowed = next_statuses(order.status, order.fulfillment_type)
        if target not in allowed:
            raise ConflictError(
                f'Зі статусу «{order.status.value}» не можна перейти в «{target.value}»',
                code='invalid_transition',
                details={'from': order.status.value, 'to': target.value, 'allowed': [s.value for s in allowed]},
            )
        if not role_may(actor.role, order.status, target):
            raise ForbiddenError('Ваша роль не може виконати цей перехід', code='transition_forbidden')

        if target is OrderStatus.completed and order.payment_status is not PaymentStatus.paid:
            raise UnprocessableError(
                'Спершу відмітьте оплату: виконати можна лише оплачене замовлення', code='payment_required',
            )

        if target is OrderStatus.cancelled:
            # гроші за скасоване замовлення: ще не взяті → платіж не відбувся (failed); уже взяті → повернуті (refunded)
            payments = await self._payments(order_id)
            for payment in payments:
                if payment.status is PaymentStatus.pending:
                    payment.status = PaymentStatus.failed
                elif payment.status is PaymentStatus.paid:
                    payment.status = PaymentStatus.refunded
            order.payment_status = summarize_payments(p.status for p in payments)

        previous = order.status
        order.status = target
        self.session.add(OrderStatusHistory(order_id=order_id, status=target, changed_by=actor.id, comment=comment))
        await self.session.commit()

        log.info('order_status_changed', order_id=order_id, from_status=previous.value, to_status=target.value, by=actor.id)
        return await self._read(order_id, actor)

    # ---------- оплата на місці ----------

    async def confirm_payment(self, actor: User, order_id: int) -> OrderRead:
        """Відмічає, що гроші отримано (готівка чи термінал: у закладі або в кур'єра).
        Повторне натискання нічого не ламає: уже оплачене замовлення просто повертається як є."""
        order = await self._load(order_id, lock=True)
        ensure_location_access(actor, order.location_id, other_location_message='Це замовлення іншого закладу')
        if order.status is OrderStatus.cancelled:
            raise ConflictError('Замовлення скасовано, оплату відмітити не можна', code='order_cancelled')

        payments = await self._payments(order_id)
        if order.payment_status is not PaymentStatus.paid:
            pending = [p for p in payments if p.status is PaymentStatus.pending]
            if not pending:
                raise ConflictError('Немає очікуваного платежу для цього замовлення', code='no_pending_payment')
            for payment in pending:
                payment.status = PaymentStatus.paid
            order.payment_status = summarize_payments(p.status for p in payments)
            await self.session.commit()
            log.info('order_payment_confirmed', order_id=order_id, by=actor.id)
        return await self._read(order_id, actor)

    # ---------- нотатки ----------

    async def update_notes(self, actor: User, order_id: int, staff_notes: str | None) -> OrderRead:
        order = await self._load(order_id)
        ensure_location_access(actor, order.location_id, other_location_message='Це замовлення іншого закладу')
        order.staff_notes = staff_notes
        await self.session.commit()
        return await self._read(order_id, actor)

    # ---------- внутрішнє ----------

    async def _load(self, order_id: int, *, lock: bool = False) -> Order:
        statement = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update()
        order = await self.session.scalar(statement)
        if order is None:
            raise NotFoundError('Замовлення не знайдено')
        return order

    async def _payments(self, order_id: int) -> list[Payment]:
        result = await self.session.scalars(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.id)
            .execution_options(populate_existing=True)
        )
        return list(result)

    async def _read(self, order_id: int, actor: User) -> OrderRead:
        """Збирає повну картку. `populate_existing`: у цій самій сесії щойно записані рядки могли лишитися
        без полів, які рахує БД (line_total), а читання на async-сесії не вміє їх «дотягти» ліниво."""
        order = await self._load(order_id)
        customer = await self.session.scalar(
            select(Customer).where(Customer.id == order.customer_id).execution_options(populate_existing=True)
        )
        items = (await self.session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
            .execution_options(populate_existing=True)
        )).all()
        payments = await self._payments(order_id)
        history_rows = (await self.session.execute(
            select(
                OrderStatusHistory.status, OrderStatusHistory.comment, OrderStatusHistory.created_at,
                User.id.label('user_id'), User.full_name.label('user_name'),
            )
            .outerjoin(User, User.id == OrderStatusHistory.changed_by)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.id)
        )).all()

        zone = None
        if order.delivery_zone_id is not None:
            zone_row = (await self.session.execute(
                select(DeliveryZone.code, DeliveryZone.name).where(DeliveryZone.id == order.delivery_zone_id)
            )).one()
            zone = ZoneRead(code=zone_row.code, name=zone_row.name)

        return OrderRead(
            id=order.id, order_number=order.order_number, location_id=order.location_id,
            source=order.source, fulfillment_type=order.fulfillment_type,
            status=order.status, payment_status=order.payment_status,
            delivery_zone=zone, delivery_address=order.delivery_address,
            subtotal_price=order.subtotal_price, delivery_price=order.delivery_price, total_price=order.total_price,
            staff_notes=order.staff_notes, created_at=order.created_at, updated_at=order.updated_at,
            customer=CustomerRead.model_validate(customer),
            items=[OrderItemRead.model_validate(item) for item in items],
            payments=[PaymentRead.model_validate(payment) for payment in payments],
            history=[
                StatusHistoryRead(
                    status=row.status, comment=row.comment, created_at=row.created_at,
                    changed_by=None if row.user_id is None else StaffBrief(id=row.user_id, full_name=row.user_name),
                )
                for row in history_rows
            ],
            allowed_statuses=allowed_for(
                actor.role, order.status, order.fulfillment_type, paid=order.payment_status is PaymentStatus.paid,
            ),
        )


def get_order_service(session: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(session)
