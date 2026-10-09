"""Instagram-native purchase conversation. Only card entry/approval opens Reap."""
import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime,timezone
from fastapi import HTTPException
from app import state
from app.agent.search import _to_candidate,recognize_and_search
from app.config import settings
from app.dm import instagram_store as store
from app.dm import instagram_personal as personal
from app.agent.profile import sensitive_text
from app.purchase import policy
from app.media.instagram import from_message,permalink,trusted_media
from app.meta import send
from app.models import ProductCandidate
from app.purchase import service
from app.reap.client import ReapError
from app.purchase.budget import handle_budget_command,check_budget
from app.web import routes as web

log=logging.getLogger('instagram-commerce')
locks:dict[str,asyncio.Lock]={}
tasks:set[asyncio.Task]=set()
watching:set[str]=set()
enrollment_watching:set[str]=set()


def spawn(coro):
    t=asyncio.create_task(coro);tasks.add(t);t.add_done_callback(tasks.discard)


def owner(sender):return 'web-ig-'+sender


def payload(uid,s,action,args=None):
    cid=state.put_callback(json.dumps({'uid':uid,'turn':s['turn'],'action':action,'args':args},sort_keys=True))
    return 'IG:'+cid


async def prompt(sender,s,text,choices):
    uid=owner(sender);s['choices']=[{'label':label,'action':action,'args':args} for label,action,args in choices]
    store.save(uid,s)
    try:
        await send.send_quick_replies(sender,text,[(label,payload(uid,s,action,args)) for label,action,args in choices])
    except Exception:
        numbered='\n'.join(f'{i+1}. {label}' for i,(label,_,_) in enumerate(choices))
        await send.send_text(sender,(text+'\n'+numbered+'\nReply with a number or the option name.')[:1000])


async def results(sender,result):
    uid=owner(sender);s={'turn':uuid.uuid4().hex,'phase':'products','candidates':[c.model_dump() for c in result.candidates[:3]]}
    store.save(uid,s)
    state.update_user(uid,pending_quote_id=None,pending_variant_id=None,pending_product_id=None,pending_option_ids='[]')
    if result.note:await send.send_text(sender,result.note[:1000])
    if not result.candidates:
        await send.send_text(sender,"I couldn't find a matching product. Send a clearer Reel or type 'search' followed by the product name.")
        return
    candidates=result.candidates[:3]
    text=('Matching listings' if result.match_type=='exact' else 'Closest matches; exact identity is unverified')+' for '+result.detected.name[:100]+'.'
    listing='\n'.join(f'{i+1}. {c.name[:100]} | {c.merchant[:35]} | {c.currency} {c.price_min:.2f}' for i,c in enumerate(candidates))
    await send.send_text(sender,(text+'\n\n'+listing+'\n\nReply 1, 2 or 3 to buy, or tap Buy below. Sandbox: no real charges or delivery.')[:1000])
    s['choices']=[{'label':str(i+1),'action':'BUY','args':c.product_id} for i,c in enumerate(candidates)];store.save(uid,s)
    elements=[]
    for c in candidates:
        e={'title':c.name[:80],'subtitle':f'{c.merchant} | {c.currency} {c.price_min:.2f}'[:80],'buttons':[{'type':'postback','title':'Buy','payload':payload(uid,s,'BUY',c.product_id)}]}
        if c.image_url:e['image_url']=c.image_url
        elements.append(e)
    try:await send._send({'recipient':{'id':sender},'message':{'attachment':{'type':'template','payload':{'template_type':'generic','elements':elements}}}})
    except Exception:log.info('carousel unavailable; numbered choices already sent')


async def next_step(sender,s):
    uid=owner(sender);pid=s['product'];detail=await web.product(pid,uid)
    chosen=s.setdefault('options',{})
    for group in detail['options']:
        values=[v for v in group['values'] if v.get('available',True)]
        if not values:raise HTTPException(409,'That variant is unavailable. Choose another product.')
        if group['name'] in chosen:continue
        if len(values)==1:chosen[group['name']]=values[0]['optionId'];continue
        s['phase']='options'
        await prompt(sender,s,'Which '+group['name'].lower()+'?',[(v['label'],'OPT',{'group':group['name'],'id':v['optionId']}) for v in values[:13]])
        return
    q=await web.quote(web.QuoteInput(product_id=pid,option_ids=list(chosen.values())),uid)
    s.update(phase='quote',quote=q);store.save(uid,s)
    summary=f"Items {q['currency']} {q['items_subtotal']:.2f}\nShipping {q['shipping']:.2f}\nTax {q['tax']:.2f}\nTotal {q['currency']} {q['final_amount']:.2f}\n\nSandbox: configured demo delivery details, no real charge or shipment."
    if not q['within_budget']:
        await send.send_text(sender,summary+'\n'+q['budget_message']);return
    await prompt(sender,s,summary,[('Confirm & pay','CONFIRM',q['quote_id']),('Cancel','CANCEL',None)])


async def report(sender,order):
    if order['status']=='COMPLETED':
        await send.send_text(sender,f"Sandbox order completed!\nOrder: {order.get('order_id') or order['checkout_id']}\nTotal: {order.get('currency') or settings.reap_default_currency} {order.get('final_amount') or 0:.2f}\nNo real charge or shipment. Reply addons for optional accessories.")
    elif order['status'] in service.TERMINAL:
        await send.send_text(sender,'Checkout '+order['status'].lower()+'. No completed order was confirmed. Send another Reel to try again.')
    else:await send.send_text(sender,'Payment is still awaiting completion on Reap. Tap the payment link above, then reply status.')


async def watch(sender,cid):
    if cid in watching:return
    watching.add(cid)
    try:
        for _ in range(60):
            try:
                order=await web.order(cid,owner(sender))
                if order['status'] in service.TERMINAL:
                    s=store.get(owner(sender));s['phase']='complete';store.save(owner(sender),s)
                    if store.first_notice(cid):await report(sender,order)
                    return
            except Exception:log.info('checkout status temporarily unavailable')
            await asyncio.sleep(3)
    finally:watching.discard(cid)


async def watch_enrollment(sender,eid,turn,attempts=240):
    if eid in enrollment_watching:return
    enrollment_watching.add(eid)
    uid=owner(sender)
    try:
        for _ in range(attempts):
            await asyncio.sleep(5)
            async with locks.setdefault(uid,asyncio.Lock()):
                s=store.get(uid)
                if s.get('phase')!='card' or s.get('turn')!=turn or state.get_user(uid).get('enrollment_id')!=eid:return
                try:
                    status=(await service.client().get_enrollment(eid)).get('status')
                    if status=='ACTIVE':
                        await send.send_text(sender,'Your card is ready. Continuing with the total you confirmed.')
                        await action(sender,s,'CARD_READY',s['quote']['quote_id'])
                        return
                    if status in ('FAILED','EXPIRED','REVOKED'):
                        await send.send_text(sender,'Card setup did not complete. Tap Fresh card link to try again.');return
                except Exception:log.info('card verification temporarily unavailable')
        await send.send_text(sender,'Card verification is taking longer. Reply card ready to check again, or tap Fresh card link.')
    finally:enrollment_watching.discard(eid)


async def action(sender,s,name,args=None):
    uid=owner(sender)
    if await personal.action(sender,s,name,args):return
    if name=='BUY':
        if s.get('phase')=='payment':
            await send.send_text(sender,'Your checkout is already in progress. Reply status before starting another order.');return
        if args not in [c['product_id'] for c in s.get('candidates',[])]:raise HTTPException(409,'Choose a product from your latest Reel.')
        s.update(product=args,options={},phase='options');s.pop('quote',None)
        state.update_user(uid,pending_product_id=args,pending_quote_id=None,pending_option_ids='[]')
        await next_step(sender,s)
    elif name=='OPT':
        choices=s.get('choices',[])
        if s.get('phase')!='options' or not any(c['action']=='OPT' and c['args']==args for c in choices):raise HTTPException(409,'Choose an available option from the current message.')
        s['options'][args['group']]=args['id'];await next_step(sender,s)
    elif name in ('CONFIRM','CARD_READY','CONFIRM_EXTRA'):
        if not s.get('quote') or args!=s['quote']['quote_id']:raise HTTPException(409,'That quote is out of date. Choose your product again.')
        if s.get('checkout'):
            await report(sender,await web.order(s['checkout'],uid));return
        q=s['quote']
        if datetime.fromisoformat(q['expires_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
            await send.send_text(sender,'That quote expired. Here is a fresh price to review.');await next_step(sender,s);return
        allowed,message=check_budget(uid,q['final_amount'],q['currency'])
        if not allowed:
            await send.send_text(sender,message or 'That quote is over your spending limit.');return
        if name=='CONFIRM_EXTRA':
            if s.get('phase')!='extra_confirm':raise HTTPException(409,'Use the current confirmation button.')
            s['extra_confirmed_quote']=args;store.save(uid,s)
        if policy.needs_extra_confirm(uid,q['final_amount']) and s.get('extra_confirmed_quote')!=args:
            s['phase']='extra_confirm'
            await prompt(sender,s,f"This exceeds your extra-check threshold: {q['currency']} {q['final_amount']:.2f}. Confirm once more before checkout.",[('Yes, pay','CONFIRM_EXTRA',args),('Cancel','CANCEL',None)])
            return
        e=await web.enrollment(web.EnrollmentInput(),uid)
        if not e['active']:
            s['phase']='card';store.save(uid,s)
            if e.get('url'):
                await send.send_url_button(sender,'One-time secure sandbox card setup. Card details stay on Reap.','Add sandbox card',e['url'])
            await prompt(sender,s,"Reap may take a few minutes to verify your card. I will continue here automatically when it is ready. If Instagram cannot create a passkey, open the Reap link in Chrome or Safari.",[('Card ready','CARD_READY',args),('Fresh card link','FRESH_CARD',args),('Cancel','CANCEL',None)])
            eid=state.get_user(uid).get('enrollment_id')
            if eid:spawn(watch_enrollment(sender,eid,s['turn']))
            return
        order=await web.checkout(web.CheckoutInput(quote_id=args,confirmed=True),uid)
        s.update(phase='payment',checkout=order['checkout_id']);store.save(uid,s)
        if order.get('approval_url') and order['status'] not in service.TERMINAL:
            await send.send_url_button(sender,f"Approve {q['currency']} {q['final_amount']:.2f} securely on Reap.",'Pay now',order['approval_url'])
        await prompt(sender,s,'I will send the order confirmation right here in this chat.',[('Check payment','STATUS',None)])
        if order['status'] in service.TERMINAL:
            result=await web.order(order['checkout_id'],uid)
            if store.first_notice(order['checkout_id']):await report(sender,result)
            s['phase']='complete';store.save(uid,s)
        else:spawn(watch(sender,order['checkout_id']))
    elif name=='FRESH_CARD':
        if s.get('phase')!='card':raise HTTPException(409,'No card setup is pending.')
        e=await web.enrollment(web.EnrollmentInput(refresh=True),uid)
        if e['active']:
            await action(sender,s,'CARD_READY',s['quote']['quote_id']);return
        await send.send_url_button(sender,'Fresh secure sandbox card setup','Add sandbox card',e['url'])
        spawn(watch_enrollment(sender,state.get_user(uid)['enrollment_id'],s['turn']))
    elif name=='STATUS':
        if not s.get('checkout'):await send.send_text(sender,'No checkout has started yet. Select a product and confirm its total.');return
        await report(sender,await web.order(s['checkout'],uid))
    elif name=='CANCEL':
        if s.get('phase')=='payment':await send.send_text(sender,'Checkout has already started. Reply status to check its result.');return
        store.save(uid,{'turn':uuid.uuid4().hex,'phase':'idle'});state.update_user(uid,pending_quote_id=None,pending_variant_id=None)
        await send.send_text(sender,'Cancelled before checkout. Send another Reel whenever you want.')


async def text(sender,message):
    value=message.strip();lower=value.lower();uid=owner(sender);s=store.get(uid)
    if sensitive_text(value):
        await send.send_text(sender,'Keep card details and secrets out of chat. Use the secure Reap payment page.');return
    if await personal.text(sender,value):return
    reply=handle_budget_command(uid,value)
    if reply:await send.send_text(sender,reply);return
    if lower in ('cancel','stop'):await action(sender,s,'CANCEL');return
    if lower in ('status','paid','payment status','check payment'):await action(sender,s,'STATUS');return
    if lower in ('confirm','pay','yes','confirm & pay','done','card ready') and s.get('quote'):
        await action(sender,s,'CARD_READY' if s.get('phase')=='card' else 'CONFIRM_EXTRA' if s.get('phase')=='extra_confirm' else 'CONFIRM',s['quote']['quote_id']);return
    choices=s.get('choices',[])
    match=re.fullmatch(r'(?:buy\s+)?([1-9])',lower)
    index=int(match.group(1))-1 if match else -1
    choice=choices[index] if 0<=index<len(choices) else next((c for c in choices if c['label'].lower()==lower),None)
    if choice:await action(sender,s,choice['action'],choice['args']);return
    if lower in ('buy','buy this','buy it') and len(s.get('candidates',[]))==1:
        await action(sender,s,'BUY',s['candidates'][0]['product_id']);return
    if lower.startswith('search '):
        await personal.catalog(sender,value[7:][:200]);return
    if lower in ('help','hi','hello','start'):
        await send.send_text(sender,"Share a Reel to shop in this chat. Try 'profile', 'settings', 'search headphones', or tell me what you own. Ask follow-up questions about your latest Reel. Sandbox only.");return
    await personal.converse(sender,value)



async def handle_one(item):
    sender=str(item.get('sender',{}).get('id',''));uid=owner(sender)
    async with locks.setdefault(uid,asyncio.Lock()):
        try:
            message=item.get('message') or {};postback=item.get('postback') or {}
            callback=postback.get('payload') or message.get('quick_reply',{}).get('payload')
            if callback:
                if not callback.startswith('IG:'):raise HTTPException(409,'That button is out of date. Reply with a choice from the latest message.')
                raw=state.get_callback(callback[3:]);c=json.loads(raw) if raw else {};s=store.get(uid)
                if c.get('uid')!=uid or c.get('turn')!=s.get('turn'):raise HTTPException(409,'That button belongs to an older conversation. Use the latest choices.')
                await action(sender,s,c['action'],c.get('args'))
            elif message.get('attachments') or permalink(message):
                if store.get(uid).get('phase')=='payment':
                    await send.send_text(sender,'Your checkout is in progress. Reply status, then send your next Reel.');return
                await send.send_text(sender,'Looking at your Reel and checking merchants now…')
                bundle=await from_message(message);result=await recognize_and_search(bundle,user_id=uid);await personal.enrich(sender,bundle,result)
            elif message.get('text'):await text(sender,str(message['text'])[:1000])
        except HTTPException as e:await send.send_text(sender,str(e.detail)[:950])
        except ReapError as e:
            if e.code=="QUOTE_EXPIRED" and store.get(uid).get("product"):
                await send.send_text(sender,"The price expired. Here is a fresh quote to review and confirm.")
                await next_step(sender,store.get(uid))
            else:await send.send_text(sender,service.friendly_error(e))
        except Exception as e:
            log.warning('Instagram flow failed: %s',type(e).__name__)
            try:await send.send_text(sender,'I could not finish that step. Please try again or type search followed by the product name.')
            except Exception:log.warning('Instagram failure reply unavailable')


def enqueue(body):
    queued=0
    for entry in body.get('entry',[]):
        for item in entry.get('messaging',[]):
            if str(item.get('recipient',{}).get('id') or entry.get('id',''))!=settings.ig_business_account_id:continue
            message=item.get('message') or {};postback=item.get('postback') or {}
            if message.get('is_echo') or message.get('is_deleted') or not item.get('sender',{}).get('id'):continue
            if not (message.get('text') or message.get('attachments') or postback.get('payload')):continue
            mid=message.get('mid') or postback.get('mid')
            if not mid and postback.get("payload") and item.get("timestamp"):
                mid=hashlib.sha256(json.dumps([item["sender"]["id"],item["timestamp"],postback["payload"]]).encode()).hexdigest()
            if not mid:continue
            if not state.first_time_seen('instagram:'+mid):continue
            spawn(handle_one(item));queued+=1
    return queued


def restore():
    for uid,s in store.pending():
        if not uid.startswith('web-ig-'):continue
        if s.get('phase')=='payment' and s.get('checkout'):spawn(watch(uid[7:],s['checkout']))
        if s.get('phase')=='card':
            eid=state.get_user(uid).get('enrollment_id')
            if eid:spawn(watch_enrollment(uid[7:],eid,s['turn']))
