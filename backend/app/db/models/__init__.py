from app.db.base import Base

# location / staff group
from app.db.models.location import Location
from app.db.models.user import User
from app.db.models.delivery_zone import DeliveryZone
from app.db.models.delivery_zone_area import DeliveryZoneArea

# dish group
from app.db.models.category import Category
from app.db.models.allergen import Allergen
from app.db.models.dish import Dish
from app.db.models.dish_location import DishLocation
from app.db.models.dish_allergen import DishAllergen

# customer group
from app.db.models.customer import Customer
from app.db.models.customer_address import CustomerAddress

# promotion group
from app.db.models.promotion import Promotion
from app.db.models.promotion_item import PromotionItem
from app.db.models.promotion_location import PromotionLocation

# ai group
from app.db.models.ai_setting import AiSetting
from app.db.models.ai_escalation_trigger import AiEscalationTrigger
from app.db.models.ai_dialog import AiDialog
from app.db.models.ai_message import AiMessage

# order group
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.order_status_history import OrderStatusHistory
from app.db.models.payment import Payment

__all__ = [
    'Base',
    'Location', 'User', 'DeliveryZone', 'DeliveryZoneArea',
    'Category', 'Allergen', 'Dish', 'DishLocation', 'DishAllergen',
    'Customer', 'CustomerAddress',
    'Promotion', 'PromotionItem', 'PromotionLocation',
    'AiSetting', 'AiEscalationTrigger', 'AiDialog', 'AiMessage',
    'Order', 'OrderItem', 'OrderStatusHistory', 'Payment',
]
