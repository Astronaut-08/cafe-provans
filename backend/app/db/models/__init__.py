from app.db.base import Base

# user group
from app.db.models.location import Location
from app.db.models.user import User

# dish group
from app.db.models.dish_location import DishLocation
from app.db.models.dish_allergen import DishAllergen
from app.db.models.dish import Dish
from app.db.models.allergen import Allergen
from app.db.models.category import Category

# customer group
from app.db.models.customer_address import CustomerAddress
from app.db.models.customer import Customer

# order group
from app.db.models.order_item import OrderItem
from app.db.models.order import Order
from app.db.models.order_status_history import OrderStatusHistory
from app.db.models.payment import Payment

# promotion group
from app.db.models.promotion_item import PromotionItem
from app.db.models.promotion_location import PromotionLocation
from app.db.models.promotion import Promotion

# ai group
from app.db.models.ai_dialog import AiDialog
from app.db.models.ai_escalation_trigger import AiEscalationTrigger
from app.db.models.ai_setting import AiSetting
from app.db.models.ai_message import AiMessage