from fastapi import APIRouter, Depends

from app.db.models.location import Location
from app.modules.delivery.schemas import (
    AddressCheckRequest, DeliveryCheck, DeliveryCheckRequest, DeliveryInfo,
)
from app.modules.delivery.service import DeliveryService, get_delivery_service
from app.modules.locations.service import get_active_location

router = APIRouter(prefix='/locations/{location_id}/delivery', tags=['Delivery'])


@router.get('', response_model=DeliveryInfo, summary='Зони доставки закладу, їхні адреси, мінімальні суми й карта')
async def get_delivery_info(
    location: Location = Depends(get_active_location),
    service: DeliveryService = Depends(get_delivery_service),
):
    return await service.get_info(location)


@router.post('/check-address', response_model=DeliveryCheck, summary='У якій зоні доставки адреса (місто й вулиця)')
async def check_delivery_address(
    data: AddressCheckRequest,
    location: Location = Depends(get_active_location),
    service: DeliveryService = Depends(get_delivery_service),
):
    """Основний спосіб: порівнює місто й вулицю зі списком, який вніс адміністратор.
    Сайту зручно давати вибір міста й вулиці зі списку `GET /delivery` (`areas`): так немає помилок у написанні."""
    return await service.check_address(location.id, data.city, data.street)


@router.post('/check', response_model=DeliveryCheck, summary='У якій зоні доставки точка (за контурами на карті)')
async def check_delivery(
    data: DeliveryCheckRequest,
    location: Location = Depends(get_active_location),
    service: DeliveryService = Depends(get_delivery_service),
):
    """Запасний спосіб за координатами. POST, а не GET, навмисно: координати дому гостя є персональними
    даними, а адреси запитів (на відміну від тіла) потрапляють у логи nginx та проксі."""
    return await service.check(location.id, data.lat, data.lng)
