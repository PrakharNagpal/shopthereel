import asyncio
import base64
import hashlib
import json
import logging
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import state
from app.agent.search import _to_candidate, recognize_and_search
from app.config import settings
from app.media.pipeline import build_bundle, bundle_from_url
from app.models import MediaBundle
from app.purchase import service
from app.purchase.budget import check_budget, set_budget
from app.reap.client import ReapError
from app.web import store

router = APIRouter(prefix='/web', dependencies=[])
log = logging.getLogger('web-commerce')
locks: dict[str, asyncio.Lock] = {}
MAX_BYTES = 20 * 1024 * 1024


def session(x_commerce_token: Annotated[str, Header()] = '', x_commerce_session: Annotated[str, Header()] = '') -> str:
    if not settings.web_api_token or not secrets.compare_digest(x_commerce_token, settings.web_api_token):
        raise HTTPException(401, 'Shopping session could not be verified.')
    if not x_commerce_session.startswith('web-') or len(x_commerce_session) > 100:
        raise HTTPException(401, 'Start a new shopping session.')
    return x_commerce_session

UID = Annotated[str, Depends(session)]


@router.get('/status')
async def status(uid: UID):
    return {'ready': bool(settings.reap_api_key and settings.openai_api_key), 'sandbox': settings.reap_simulate_checkout,
            'country': settings.reap_default_country, 'currency': settings.reap_default_currency}


@router.post('/analyze')
async def analyze(uid: UID, media: UploadFile | None = File(None), url: str = Form(''), context: str = Form(''), budget: float | None = Form(None)):
    if budget is not None:
        if budget <= 0 or not budget < 1_000_000:
            raise HTTPException(400, 'Enter a valid positive budget.')
        set_budget(uid, budget, settings.reap_default_currency)
    else:
        state.update_user(uid, budget_per_order=None, budget_currency=None)
    if not media and not url:
        raise HTTPException(400, 'Send a public Instagram Reel or upload its video.')
    try:
        if media:
            data = await media.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise HTTPException(413, 'Use a file smaller than 20 MB.')
            if not data:
                raise HTTPException(400, 'The uploaded file is empty.')
            rid = hashlib.sha256(data).hexdigest()
            if media.content_type in ('image/jpeg', 'image/png', 'image/webp'):
                # ffmpeg normalizes a still image into the repo's JPEG frame contract.
                with tempfile.TemporaryDirectory() as d:
                    path = Path(d) / 'image'; path.write_bytes(data)
                    frame = Path(d) / 'frame.jpg'
                    proc = await asyncio.create_subprocess_exec('ffmpeg','-y','-i',str(path),'-vf','scale=768:-2','-frames:v','1',str(frame),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
                    await asyncio.wait_for(proc.wait(), 30)
                    if proc.returncode or not frame.exists():
                        raise HTTPException(400,'That image could not be read.')
                    bundle = MediaBundle(reel_id=rid, frames_b64=[base64.b64encode(frame.read_bytes()).decode()], user_hint=context[:1000] or None)
            elif media.content_type in ('video/mp4', 'video/quicktime', 'video/webm'):
                with tempfile.TemporaryDirectory() as d:
                    path = Path(d) / 'video.mp4'; path.write_bytes(data)
                    bundle = await build_bundle(path, rid, None, context[:1000] or None)
            else:
                raise HTTPException(400, 'Upload an MP4, MOV, WebM, JPEG, PNG or WebP file.')
        else:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in ('instagram.com', 'www.instagram.com') or not parsed.path.startswith(('/reel/', '/reels/', '/p/')):
                raise HTTPException(400, 'Use a public Instagram Reel link.')
            rid = hashlib.sha256(url.split('?')[0].encode()).hexdigest()
            bundle = await bundle_from_url(url[:1000], rid, None, context[:1000] or None)
            # The downloader uses a temporary video; clean it after extracting the bundle.
            (Path('/tmp') / f'{hashlib.sha1(rid.encode()).hexdigest()[:16]}.mp4').unlink(missing_ok=True)
        if not bundle.frames_b64:
            raise HTTPException(400, 'No video frames could be read. Try uploading the Reel video.')
        result = await recognize_and_search(bundle, user_id=uid)
        return {**result.model_dump(), 'evidence': {'frames': len(bundle.frames_b64), 'transcript_available': bool(bundle.transcript)}, 'sandbox':settings.reap_simulate_checkout}
    except HTTPException:
        raise
    except Exception as e:
        log.warning('analysis failed: %s', type(e).__name__)
        raise HTTPException(502, 'The Reel could not be analyzed. Try uploading the video or a clear product image.') from None


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=200)


@router.post('/search')
async def search(body: SearchInput, uid: UID):
    res = await service.client().search_products(body.query, limit=8)
    return {'candidates': [_to_candidate(p).model_dump() for p in res.get('products',[])], 'sandbox':settings.reap_simulate_checkout}


@router.get('/products/{pid}')
async def product(pid: str, uid: UID):
    data = await service.client().product_details([pid])
    prods = data.get('products', [])
    if not prods:
        raise HTTPException(404, 'This product is no longer available.')
    p = prods[0]
    return {'product_id':p['id'], 'name':p['name'], 'options':p.get('options',[]), 'default_variant':p.get('defaultVariant'), 'requires_shipping':p.get('requiresShipping',True)}


class QuoteInput(BaseModel):
    product_id: str = Field(max_length=100)
    option_ids: list[str] = Field(default_factory=list, max_length=10)
    email: str = Field(default='', max_length=254)
    shipping_address: dict | None = None


@router.post('/quote')
async def quote(body: QuoteInput, uid: UID):
    async with locks.setdefault(uid, asyncio.Lock()):
        variant = await service.resolve_variant(body.product_id, body.option_ids)
        shipping = body.shipping_address if body.shipping_address else json.loads(settings.demo_shipping_json)
        email = body.email or settings.demo_email
        if '@' not in email:
            raise HTTPException(400,'Enter a valid email address.')
        q = await service.client().create_quote({'items':[{'variantId':variant,'quantity':1}], 'email':email, 'shippingAddress':shipping})
        opts = q.get('shippingOptions') or []
        if len(opts) > 1:
            cheapest = min(opts,key=lambda o:service._money(o['price']))
            if not cheapest.get('selected'):
                q = await service.client().set_shipping_option(q['id'], {'shippingOptionId':cheapest['id']})
        ab = q['amountBreakdown']; final=service._money(ab['finalAmount']);cur=ab['finalAmount']['currency']
        allowed,msg=check_budget(uid,final,cur)
        # Store only the price, quote ID and expiry; never retain shipping or email here.
        saved={'id':q['id'],'expiresAt':q['expiresAt'],'amount':final,'currency':cur}
        store.save_quote(uid,saved)
        state.update_user(uid,pending_quote_id=q['id'],pending_quote_amount=final,pending_variant_id=variant)
        return {'quote_id':q['id'],'items_subtotal':service._money(ab['itemsSubtotal']),'shipping':service._money(ab['shipping']),'tax':service._money(ab['tax']), 'final_amount':final,'currency':cur,'expires_at':q['expiresAt'],'within_budget':allowed,'budget_message':msg,'sandbox':settings.reap_simulate_checkout}


class EnrollmentInput(BaseModel):
    refresh: bool = False


@router.post('/enrollment')
async def enrollment(body: EnrollmentInput, uid: UID):
    async with locks.setdefault(uid, asyncio.Lock()):
        current = await service.enrollment_state(uid)
        if current == 'ACTIVE':
            return {'active': True, 'pending': False, 'url': None, 'sandbox': settings.reap_simulate_checkout}
        if current == 'PENDING' and not body.refresh:
            return {'active': False, 'pending': True, 'url': None, 'sandbox': settings.reap_simulate_checkout}
        url = await service.ensure_enrollment(uid)
        return {'active': url is None, 'pending': False, 'url': url, 'sandbox': settings.reap_simulate_checkout}


class CheckoutInput(BaseModel):
    quote_id: str = Field(max_length=100)
    confirmed: bool = False


@router.post('/checkout')
async def checkout(body: CheckoutInput, uid: UID):
    if not body.confirmed:
        raise HTTPException(400,'Approve the displayed total before paying.')
    async with locks.setdefault(uid, asyncio.Lock()):
        record=store.get_quote(uid,body.quote_id)
        if not record:
            raise HTTPException(404,'That quote does not belong to this session.')
        q,cid=record
        if cid:
            return service._to_order(await service.client().get_checkout(cid)).model_dump()
        u=state.get_user(uid)
        if u.get('pending_quote_id') != body.quote_id:
            raise HTTPException(409,'A newer quote is available. Review its total first.')
        if datetime.fromisoformat(q['expiresAt'].replace('Z','+00:00')) <= datetime.now(timezone.utc):
            raise HTTPException(409,'This quote expired. Get a new quote and review the updated price.')
        allowed,msg=check_budget(uid,q['amount'],q['currency'])
        if not allowed:
            raise HTTPException(409,msg)
        eid=u.get('enrollment_id')
        if not eid or (await service.client().get_enrollment(eid)).get('status') != 'ACTIVE':
            raise HTTPException(409,'Add your sandbox card on Reap, then return and check card status.')
        result=await service.client().create_checkout(body.quote_id,eid,settings.reap_return_url,idempotency_key='web-'+body.quote_id)
        order=service._to_order(result)
        store.save_checkout(uid,body.quote_id,order.checkout_id)
        state.update_user(uid,pending_checkout_id=order.checkout_id)
        return order.model_dump()


@router.get('/checkout/{cid}')
async def order(cid:str,uid:UID):
    if not store.owns_checkout(uid,cid):
        raise HTTPException(404,'This order does not belong to your shopping session.')
    order=await service.poll_checkout(cid)
    if order.status=='COMPLETED':
        state.save_order(cid,uid,order.order_id,order.final_amount,order.currency)
    return {**order.model_dump(),'sandbox':settings.reap_simulate_checkout}


class HandoffInput(BaseModel):
    result: dict


@router.post('/handoff')
async def handoff(body: HandoffInput, uid: UID):
    from app.models import RecognitionResult
    RecognitionResult.model_validate(body.result)
    token=store.save_handoff(body.result)
    return {'url':settings.public_base_url+'/shop?reel='+token}


@router.get('/handoff/{token}')
async def open_handoff(token: str, uid: UID):
    result=store.get_handoff(token)
    if not result:
        raise HTTPException(404,'This Reel result expired. Send or upload the Reel again.')
    return result
