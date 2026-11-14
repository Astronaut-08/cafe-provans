from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    '''Base class for all database models.'''
    pass

from models.location import Location
from models.user import User
from models.dish_location import DishLocation
from models.dish_allergen import DishAllergen
from models.dish import Dish
from models.allergen import Allergen
from models.category import Category
from models.customer_address import CustomerAddress
from models.customer import Customer
from models.order_item import OrderItem
from models.order import Order
from models.promotion_item import PromotionItem
from models.promotion_location import PromotionLocation
from models.promotion import Promotion