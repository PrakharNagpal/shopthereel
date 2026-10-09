"""Real video + OpenAI + Reap; outgoing Instagram messages captured, not sent.
Run: .venv/bin/python -m scripts.instagram_e2e
"""
import asyncio,json,tempfile,hashlib
from pathlib import Path
from unittest.mock import AsyncMock,patch
from app.config import settings
from app.dm import instagram as ig,instagram_store as store
from app.media.pipeline import build_bundle
from app.purchase import service

async def run():
 video=Path('work/test-product-reel.mp4')
 bundle=await build_bundle(video,hashlib.sha256(video.read_bytes()).hexdigest(),None)
 original_db=settings.db_path
 with tempfile.TemporaryDirectory() as d:
  settings.db_path=d+'/instagram-test.db'
  outputs=[]
  async def text(sender,message):outputs.append({'type':'text','text':message})
  async def prompt(sender,message,choices):outputs.append({'type':'choices','text':message,'choices':[label for label,_ in choices]})
  async def link(sender,message,title,url):outputs.append({'type':'Reap hosted link','title':title,'https':url.startswith('https://')})
  sender='native-fixture';uid=ig.owner(sender)
  with patch.object(ig.send,'send_text',side_effect=text),patch.object(ig.send,'send_quick_replies',side_effect=prompt),patch.object(ig.send,'send_url_button',side_effect=link),patch.object(ig.send,'_send',new=AsyncMock()),patch.object(ig,'from_message',new=AsyncMock(return_value=bundle)):
   await ig.handle_one({'sender':{'id':sender},'message':{'attachments':[{'type':'ig_reel','payload':{'url':'https://lookaside.fbsbx.com/ig_messaging_cdn/?fixture=video'}}]}})
   s=store.get(uid);assert s.get('candidates'),outputs
   print('PASS real video + OpenAI + Reap merchant candidates')
   await ig.text(sender,'1')
   for _ in range(10):
    s=store.get(uid)
    if s.get('phase')!='options':break
    first=s['choices'][0];await ig.action(sender,s,first['action'],first['args'])
   s=store.get(uid);assert s.get('phase')=='quote',outputs
   print('PASS product and variant choices inside chat; real quote:',s['quote']['currency'],s['quote']['final_amount'])
   await ig.text(sender,'confirm')
   s=store.get(uid)
   if s.get('checkout'):
    order=await ig.web.order(s['checkout'],uid)
    if order['status']=='COMPLETED':
     assert order.get('order_id'), 'Completed order missing order ID'
     print('PASS actual Reap sandbox checkout COMPLETED with order ID')
    else:
     assert order['status']=='REQUIRES_ACTION',order['status']
     assert order.get('approval_url'), 'Missing hosted payment approval URL'
     assert any(o['type']=='Reap hosted link' and o['title']=='Pay now' for o in outputs)
     print('PASS actual Reap checkout and Pay now DM button; hosted user approval still required')
   else:
    assert s.get('phase')=='card';assert any(o['type']=='Reap hosted link' and o['https'] for o in outputs)
    print('PASS confirm in chat produces actual secure Reap card-setup link; payment not completed')
   assert not any('/shop' in str(o) for o in outputs)
   print('PASS conversation never sends users to the shopping website')
   Path('work/instagram-test-transcript.json').write_text(json.dumps(outputs,indent=2))
   print('No actual Instagram DM was sent by this test. Provider calls were live sandbox calls.')
   for task in list(ig.tasks):task.cancel()
   if ig.tasks:await asyncio.gather(*list(ig.tasks),return_exceptions=True)
 settings.db_path=original_db
 await service.client().aclose()

asyncio.run(run())
