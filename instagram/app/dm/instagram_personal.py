"""Personal advice and rule menus rendered through the native Instagram conversation."""
import uuid
from fastapi import HTTPException
from app.agent import profile, conversation, personalize, recommend
from app.agent.search import gather_candidates
from app.models import DetectedProduct, RecognitionResult
from app.purchase import policy, service
from app.dm import instagram_store as store
from app.meta import send

async def enrich(sender, bundle, result):
    from app.dm import instagram as ig
    uid=ig.owner(sender)
    p=profile.load_profile(uid)
    advice=await personalize.advise(bundle,result.detected,uid,result.candidates) if any(p.get(f) for f in profile.FIELDS) else {}
    indices=[]
    for i in advice.get('recommended_indices',[]):
        if type(i) is int and 0<=i<len(result.candidates) and i not in indices:indices.append(i)
    if indices:
        indices += [i for i in range(len(result.candidates)) if i not in indices]
        result.candidates=[result.candidates[i] for i in indices]
        result.candidates[0].badge='For your profile'
    result.note='\n\n'.join(n for n in (result.note,advice.get('note')) if n) or None
    conversation.remember_reel(uid,bundle,result,advice)
    await ig.results(sender,result)
    s=store.get(uid)
    if advice.get('oven_alternative'):
        await send.send_quick_replies(sender,'You can also use equipment you already own.', [('Use my oven',ig.payload(uid,s,'OVEN',bundle.reel_id))])

async def catalog(sender, query, candidates=None):
    from app.dm import instagram as ig
    uid=ig.owner(sender)
    if store.get(uid).get('phase')=='payment':raise HTTPException(409,'Your checkout is in progress. Reply status before browsing another order.')
    if candidates is None:
        pooled=await gather_candidates([query[:200]]);candidates=[c for _,c in pooled]
    candidates=[c for c in candidates if not profile.excluded(c.name,profile.load_profile(uid))][:3]
    result=RecognitionResult(detected=DetectedProduct(name=query[:200],category='search',brand_source='none',attributes=[],queries=[query[:200]],best_frame=0,confidence=1),match_type='similar' if candidates else 'none',candidates=candidates,note='Catalog suggestions. Confirm fit and compatibility before buying.')
    await ig.results(sender,result)

async def menu(sender,s):
    from app.dm import instagram as ig
    uid=ig.owner(sender)
    s.setdefault('shopping_choices',s.get('choices',[]))
    await ig.prompt(sender,s,'Your spending rules:\n'+policy.summary(uid),[(r.title,'RULE',k) for k,r in policy.RULES.items()]+[('Resume buying' if policy.is_paused(uid) else 'Pause buying','PAUSE',None),('Done','RULE_DONE',None)])

async def action(sender,s,name,args):
    from app.dm import instagram as ig
    uid=ig.owner(sender)
    if name=='RULE':
        if args not in policy.RULES:raise HTTPException(400,'Choose a spending rule from the menu.')
        rule=policy.RULES[args];s['rule_input']=args
        await ig.prompt(sender,s,rule.question+'. Type a number or choose:',[(policy.fmt(rule,v),'RULE_VALUE',{'key':args,'value':v}) for v in rule.presets]+[('No limit','RULE_VALUE',{'key':args,'value':None}),('Back','RULE_MENU',None)])
    elif name=='RULE_VALUE':
        key=args.get('key');value=args.get('value')
        if key not in policy.RULES or s.get('rule_input')!=key:raise HTTPException(409,'Choose the rule again.')
        if value is not None and (not isinstance(value,(int,float)) or not 0<value<1_000_000 or key=='daily' and value!=int(value)):raise HTTPException(400,'Enter a positive number; daily orders must be a whole number.')
        policy.set_rule(uid,key,value);s.pop('rule_input',None)
        await send.send_text(sender,'Saved your spending rule.');await menu(sender,s)
    elif name=='RULE_MENU':
        s.pop('rule_input',None);await menu(sender,s)
    elif name=='RULE_DONE':
        s.pop('rule_input',None);s['choices']=s.pop('shopping_choices',[]);store.save(uid,s)
        await send.send_text(sender,'Rules saved. Share a Reel or continue with the product buttons above.')
    elif name=='PAUSE':
        policy.set_paused(uid,not policy.is_paused(uid));await menu(sender,s)
    elif name=='INVENTORY':
        context=conversation.read_context(uid);pending=context.get('pending_inventory')
        if not pending or args.get('nonce')!=pending.get('nonce'):raise HTTPException(409,'That memory update expired. Tell me again.')
        context.pop('pending_inventory',None);conversation.write_context(uid,context)
        if args.get('yes'):
            conversation.record_inventory(uid,pending['item'],pending['field'],pending['present'])
            await send.send_text(sender,f"Saved: you {'have' if pending['present'] else 'do not have'} {pending['item']}.")
        else:await send.send_text(sender,'Your inventory was not changed.')
        s['choices']=s.pop('memory_choices',[]);store.save(uid,s)
    elif name in ('OVEN','OVENSHOP'):
        reel=conversation.read_context(uid).get('reel',{});advice=reel.get('advice',{})
        if not any('oven' in item.casefold() for item in profile.load_profile(uid).get('home',[])):raise HTTPException(409,'Your current profile does not list an oven. Update it or send the recipe again.')
        if reel.get('reel_id')!=args or not advice.get('oven_alternative'):raise HTTPException(409,'Send the recipe Reel again so I can adapt it.')
        if name=='OVEN':
            await send.send_text(sender,advice['oven_alternative'][:1000])
            if advice.get('alternative_queries'):
                await send.send_quick_replies(sender,'Check your pantry first. Browse individual missing items?', [('Browse missing items',ig.payload(uid,s,'OVENSHOP',args))])
        else:
            await send.send_text(sender,'These are individual catalog suggestions, not a complete recipe basket.')
            pooled=await gather_candidates(advice.get('alternative_queries',[])[:3]);await catalog(sender,'recipe ingredients or accessories',[c for _,c in pooled])
    elif name=='ADDONS':
        if s.get('phase')!='complete' or not s.get('product'):raise HTTPException(409,'Complete an order first, then ask for add-ons.')
        bought=next((c for c in s.get('candidates',[]) if c['product_id']==s['product']),None)
        if not bought:raise HTTPException(409,'No completed product is available for recommendations.')
        order=await ig.web.order(s['checkout'],uid)
        if order['status']!='COMPLETED':raise HTTPException(409,'Add-ons are available after your order completes.')
        candidates=await recommend.suggest_addons(bought['name'],bought['product_id'],user_id=uid,limit=3)
        await catalog(sender,'optional add-ons for '+bought['name'],candidates)
    else:return False
    return True

async def text(sender,value):
    from app.dm import instagram as ig
    uid=ig.owner(sender);lower=value.strip().lower();s=store.get(uid) or {'turn':uuid.uuid4().hex,'phase':'idle'}
    if lower=='profile':await send.send_text(sender,profile.describe_profile(uid)[:1000]);return True
    if lower=='profile clear':
        profile.clear_profile(uid);await send.send_text(sender,'Your saved profile, Reel context and conversation memory have been cleared.');return True
    if lower.startswith('profile set '):
        field,_,data=value[12:].partition(' ')
        try:profile.update_profile(uid,field.lower(),data);reply=profile.describe_profile(uid)
        except ValueError as e:reply=str(e)
        await send.send_text(sender,reply[:1000]);return True
    if lower in ('settings','rules','limits','menu','spending rules'):
        s.pop('rule_input',None);await menu(sender,s);return True
    if lower in ('pause buying','resume buying'):
        policy.set_paused(uid,lower=='pause buying');await send.send_text(sender,policy.summary(uid));return True
    if s.get('rule_input') and lower not in ('cancel','stop'):
        try:value_num=None if lower in ('off','no limit') else float(lower.removeprefix('sgd').strip().lstrip('$'))
        except ValueError:await send.send_text(sender,'Send a positive number, or type menu to go back.');return True
        await action(sender,s,'RULE_VALUE',{'key':s['rule_input'],'value':value_num});return True
    pending=conversation.read_context(uid).get('pending_inventory')
    if pending and lower in ('yes','yes, remember','no','no thanks'):
        await action(sender,s,'INVENTORY',{'nonce':pending['nonce'],'yes':lower.startswith('yes')});return True
    if lower=='use my oven':
        await action(sender,s,'OVEN',conversation.read_context(uid).get('reel',{}).get('reel_id'));return True
    if lower in ('addons','add-ons'):
        await action(sender,s,'ADDONS',None);return True
    if lower=='demo air fryer':
        if s.get('phase')=='payment':raise HTTPException(409,'Reply status before starting a demo.')
        await send.send_text(sender,'Demo scene, not a scan of a real Reel: air-fryer baked oats. Using only your saved profile. Catalog and personal advice are live.')
        bundle,detected=personalize.mock_air_fryer_scene();pooled=await gather_candidates(detected.queries)
        candidates=[c for _,c in pooled if not profile.excluded(c.name,profile.load_profile(uid))][:3]
        await enrich(sender,bundle,RecognitionResult(detected=detected,match_type='similar' if candidates else 'none',candidates=candidates));return True
    return False

async def converse(sender,value):
    from app.dm import instagram as ig
    uid=ig.owner(sender);answer=await conversation.respond(uid,value);s=store.get(uid) or {'turn':uuid.uuid4().hex,'phase':'idle'}
    if answer.get('intent')=='remember':
        s['memory_choices']=s.get('choices',[])
        await ig.prompt(sender,s,answer['reply'],[('Yes, remember','INVENTORY',{'nonce':answer['nonce'],'yes':True}),('No thanks','INVENTORY',{'nonce':answer['nonce'],'yes':False})])
    else:await send.send_text(sender,answer['reply'][:1000])
    if answer.get('intent')=='search' and answer.get('query'):await catalog(sender,answer['query'])
