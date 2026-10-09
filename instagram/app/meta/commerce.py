import secrets
from typing import Annotated
from fastapi import APIRouter,Header,HTTPException
from app.config import settings
from app.dm import instagram
router=APIRouter(prefix='/instagram')

@router.post('/events')
async def events(body:dict,x_commerce_token:Annotated[str,Header()]=''):
    if not settings.web_api_token or not secrets.compare_digest(x_commerce_token,settings.web_api_token):raise HTTPException(401)
    return {'received':True,'queued':instagram.enqueue(body)}
