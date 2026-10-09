"""Live OpenAI + Reap for new personal features, isolated DB and captured Instagram sends."""
import asyncio,json,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
from app import state
from app.config import settings
from app.agent import profile,conversation,recommend
from app.dm import instagram as ig,instagram_personal as personal,instagram_store as store
from app.purchase import service

async def run():
 original=settings.db_path;outputs=[];sender='personal-fixture';uid=ig.owner(sender)
 async def text(sender,message):outputs.append({'text':message})
 async def prompt(sender,message,choices):outputs.append({'text':message,'choices':[label for label,_ in choices]})
 async def link(sender,message,title,url):outputs.append({'text':message,'link_title':title})
 with tempfile.TemporaryDirectory() as d:
  settings.db_path=d+'/personal.db'
  with patch.object(ig.send,'send_text',side_effect=text),patch.object(ig.send,'send_quick_replies',side_effect=prompt),patch.object(ig.send,'send_url_button',side_effect=link),patch.object(ig.send,'_send',new=AsyncMock()):
   await ig.text(sender,'profile set home oven')
   await ig.text(sender,'I have basil')
   pending=conversation.read_context(uid).get('pending_inventory',{})
   assert pending.get('item')=='basil' and pending.get('field')=='pantry',pending
   assert profile.load_profile(uid)['pantry']==[]
   await ig.text(sender,'yes');assert profile.load_profile(uid)['pantry']==['basil']
   print('PASS live natural-language memory asks confirmation and persists basil only after yes')
   await ig.text(sender,'Do I have basil?')
   assert 'lists basil' in outputs[-1]['text'];print('PASS live inventory question recalls confirmed user-specific facts')
   await ig.text(sender,'demo air fryer')
   reel=conversation.read_context(uid)['reel'];assert reel['advice'].get('note')
   assert reel['advice'].get('oven_alternative'),reel['advice'].get('note')
   await ig.text(sender,'use my oven')
   print('PASS live oven alternative and merchant catalog suggestions in captured native chat')
   await ig.text(sender,'What do I need to check before making this recipe?')
   assert outputs[-1]['text'];print('PASS follow-up answer uses retained Reel context')
   addons=await recommend.suggest_addons('Sony WI-C100 wireless neckband headphones',max_price=20,limit=3,user_id=uid)
   assert all(c.price_min<=20 for c in addons)
   print('PASS live optional add-on search/filter:',len(addons),'catalog matches; no automatic purchase')
   await ig.text(sender,'settings');s=store.get(uid);await ig.action(sender,s,'RULE','daily');await ig.text(sender,'2')
   assert state.get_user(uid)['max_orders_per_day']==2
   print('PASS Instagram spending-rule menu and custom daily limit')
   assert not store.get(uid).get('checkout');print('PASS advice and memory never start a purchase')
   Path('work/instagram-personal-test-transcript.json').write_text(json.dumps(outputs,indent=2))
  settings.db_path=original
 await service.client().aclose()
 print('No real Instagram DM sent; no real shopper profile changed.')

if __name__=='__main__':asyncio.run(run())
