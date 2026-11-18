from fastapi import APIRouter, Depends

from app.modules.allergens.schemas import AllergenRead
from app.modules.allergens.service import AllergenService, get_allergen_service

router = APIRouter(prefix='/allergens', tags=['Allergens'])


@router.get('', response_model=list[AllergenRead], summary='Довідник алергенів')
async def list_allergens(service: AllergenService = Depends(get_allergen_service)):
    return await service.list()
