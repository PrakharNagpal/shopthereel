import asyncio
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
from app import state
from app.config import settings
from app.dm import instagram as ig,instagram_store as store
from app.models import DetectedProduct,ProductCandidate,RecognitionResult,MediaBundle

class InstagramChatTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.saved=(settings.db_path,settings.demo_enrollment_id,settings.ig_business_account_id,settings.demo_email,settings.demo_shipping_json)
  settings.db_path=self.tmp.name+'/ig.db';settings.demo_enrollment_id='';settings.ig_business_account_id='bot';settings.demo_email='buyer@example.test';settings.demo_shipping_json='{}'
  self.sender='buyer';self.uid=ig.owner(self.sender);self.messages=[];self.jobs=[]
  self.client=AsyncMock()
  self.client.product_details.return_value={'products':[{'id':'product-1','name':'Headphones','options':[{'name':'Color','values':[{'label':'BLACK','optionId':'black','available':True},{'label':'WHITE','optionId':'white','available':True}]}],'defaultVariant':{'id':'variant-black'}}]}
  self.client.resolve_variant.return_value={'id':'variant-black'}
  self.client.create_quote.return_value={'id':'quote-1','expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),'shippingOptions':[],'amountBreakdown':{'itemsSubtotal':{'amount':40,'currency':'SGD'},'shipping':{'amount':4.9,'currency':'SGD'},'tax':{'amount':{'amount':0,'currency':'SGD'}},'finalAmount':{'amount':44.9,'currency':'SGD'}}}
  self.client.get_enrollment.return_value={'status':'REQUIRES_ACTION','nextAction':{'url':'https://sandbox.example/card'}}
  self.client.create_enrollment.return_value={'id':'enrollment-1','status':'REQUIRES_ACTION','nextAction':{'url':'https://sandbox.example/card'}}
  self.client.create_checkout.return_value={'id':'checkout-1','status':'REQUIRES_ACTION','amount':{'amount':44.9,'currency':'SGD'},'nextAction':{'url':'https://sandbox.example/pay'}}
  self.client.get_checkout.return_value={'id':'checkout-1','status':'COMPLETED','orderId':'order-1','finalAmount':{'amount':44.9,'currency':'SGD'}}
  result=RecognitionResult(detected=DetectedProduct(name='Headphones',category='electronics',brand_source='none',attributes=['black'],queries=['headphones'],best_frame=0,confidence=.8),match_type='similar',candidates=[ProductCandidate(product_id='product-1',name='Headphones',merchant='Merchant',price_min=40,price_max=40,currency='SGD')])
  async def text(sender,body):self.messages.append(('text',sender,body))
  async def prompt(sender,body,choices):self.messages.append(('prompt',sender,body,choices))
  async def link(sender,body,title,url):self.messages.append(('link',sender,title,url))
  def spawn(coro):self.jobs.append(coro)
  self.patches=[patch('app.purchase.service.client',return_value=self.client),patch.object(ig.send,'send_text',side_effect=text),patch.object(ig.send,'send_quick_replies',side_effect=prompt),patch.object(ig.send,'send_url_button',side_effect=link),patch.object(ig.send,'_send',new=AsyncMock()),patch.object(ig,'spawn',side_effect=spawn),patch.object(ig,'from_message',new=AsyncMock(return_value=MediaBundle(reel_id='fixture',frames_b64=['fixture']))),patch.object(ig,'recognize_and_search',new=AsyncMock(return_value=result))]
  for p in self.patches:p.start()
 async def asyncTearDown(self):
  for coro in self.jobs:coro.close()
  for p in self.patches:p.stop()
  settings.db_path,settings.demo_enrollment_id,settings.ig_business_account_id,settings.demo_email,settings.demo_shipping_json=self.saved;self.tmp.cleanup()
 async def message(self,text=None,payload=None,sender=None):
  m={'text':text} if text is not None else {'quick_reply':{'payload':payload}}
  await ig.handle_one({'sender':{'id':sender or self.sender},'message':m})
 async def reel(self):
  await ig.handle_one({'sender':{'id':self.sender},'message':{'attachments':[{'type':'ig_reel','payload':{'url':'https://lookaside.fbsbx.com/ig_messaging_cdn/?fixture=1'}}]}})
 async def quote(self):
  await self.reel();await self.message('buy 1');await self.message('black')
 def choice(self,action):
  s=store.get(self.uid);c=next(c for c in s['choices'] if c['action']==action)
  return ig.payload(self.uid,s,action,c['args'])
 async def test_reel_to_payment_link_and_order_entirely_in_chat(self):
  await self.quote();self.assertEqual(store.get(self.uid)['phase'],'quote');self.client.create_checkout.assert_not_awaited()
  await self.message(payload=self.choice('CONFIRM'))
  self.assertEqual(store.get(self.uid)['phase'],'card');self.assertTrue(any(m[0]=='link' and m[3].endswith('/card') for m in self.messages))
  self.client.get_enrollment.return_value={'status':'ACTIVE'}
  await self.message('done');self.assertEqual(store.get(self.uid)['phase'],'payment')
  self.assertTrue(any(m[0]=='link' and m[3].endswith('/pay') for m in self.messages))
  await ig.watch(self.sender,'checkout-1')
  self.assertTrue(any(m[0]=='text' and 'order-1' in m[2] for m in self.messages))
  self.assertEqual(state.orders_today(self.uid),1)
  self.assertTrue(all(m[1]==self.sender for m in self.messages))
  self.assertFalse(any('/shop' in str(m) for m in self.messages))
  self.assertEqual(self.client.create_checkout.call_args.kwargs['idempotency_key'],'web-quote-1')
 async def test_text_and_button_confirmation_cannot_double_charge(self):
  await self.quote();callback=self.choice('CONFIRM');self.client.get_enrollment.return_value={'status':'ACTIVE'};state.update_user(self.uid,enrollment_id='enrollment-1')
  await self.message(payload=callback);await self.message('confirm');self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_other_sender_cannot_use_buy_button(self):
  await self.reel();await self.message(payload=self.choice('BUY'),sender='other');self.client.product_details.assert_not_awaited()
  self.assertTrue(any('older conversation' in m[2] for m in self.messages if m[0]=='text'))
 async def test_cancel_invalidates_buttons_and_quote(self):
  await self.quote();callback=self.choice('CONFIRM');await self.message('cancel');await self.message(payload=callback);self.client.create_checkout.assert_not_awaited();self.assertIsNone(state.get_user(self.uid).get('pending_quote_id'))
 async def test_expired_price_requires_new_confirmation(self):
  await self.quote();s=store.get(self.uid);s['quote']['expires_at']='2020-01-01T00:00:00Z';store.save(self.uid,s)
  await self.message('confirm');self.client.create_checkout.assert_not_awaited();self.assertEqual(self.client.create_quote.await_count,2)
 async def test_quote_over_budget_has_no_confirm_button(self):
  await self.message('budget 10');await self.quote();self.assertFalse(store.get(self.uid)['quote']['within_budget']);self.client.create_checkout.assert_not_awaited()
 async def test_replayed_signed_event_echo_and_wrong_account_skipped(self):
  item={'sender':{'id':'buyer'},'recipient':{'id':'bot'},'message':{'mid':'one','text':'hi'}};body={'entry':[{'id':'bot','messaging':[item]}]}
  self.assertEqual(ig.enqueue(body),1);self.assertEqual(ig.enqueue(body),0)
  item['message']={'mid':'two','text':'hi','is_echo':True};self.assertEqual(ig.enqueue(body),0)
  item['message']={'mid':'three','text':'hi'};item['recipient']['id']='other';self.assertEqual(ig.enqueue(body),0)
 async def test_postback_without_mid_uses_timestamp_dedup(self):
  item={'sender':{'id':'buyer'},'recipient':{'id':'bot'},'timestamp':12345,'postback':{'payload':'IG:test'}}
  body={'entry':[{'id':'bot','messaging':[item]}]};self.assertEqual(ig.enqueue(body),1);self.assertEqual(ig.enqueue(body),0)
 async def test_card_pending_does_not_reuse_or_replace_single_use_link(self):
  await self.quote();await self.message('confirm');await self.message('card ready')
  self.assertEqual(self.client.create_enrollment.await_count,1)
  self.assertEqual(sum(m[0]=='link' and m[3].endswith('/card') for m in self.messages),1)
  self.assertEqual(store.get(self.uid)['phase'],'card')
 async def test_card_activation_resumes_confirmed_checkout(self):
  await self.quote();await self.message('confirm');s=store.get(self.uid)
  self.client.get_enrollment.return_value={'status':'ACTIVE'}
  with patch.object(ig.asyncio,'sleep',new=AsyncMock()):
   await ig.watch_enrollment(self.sender,'enrollment-1',s['turn'],attempts=1)
  self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_cancel_stops_enrollment_resume(self):
  await self.quote();await self.message('confirm');turn=store.get(self.uid)['turn'];await self.message('cancel')
  self.client.get_enrollment.return_value={'status':'ACTIVE'}
  with patch.object(ig.asyncio,'sleep',new=AsyncMock()):
   await ig.watch_enrollment(self.sender,'enrollment-1',turn,attempts=1)
  self.client.create_checkout.assert_not_awaited()
 async def test_fresh_card_replaces_enrollment(self):
  await self.quote();await self.message('confirm');self.client.create_enrollment.return_value={'id':'enrollment-2','nextAction':{'url':'https://sandbox.example/new-card'}}
  await self.message(payload=self.choice('FRESH_CARD'))
  self.assertEqual(state.get_user(self.uid)['enrollment_id'],'enrollment-2')
  self.assertEqual(self.client.create_enrollment.await_count,2)
 async def test_terminal_checkout_does_not_block_next_reel(self):
  await self.quote();self.client.get_enrollment.return_value={'status':'ACTIVE'};state.update_user(self.uid,enrollment_id='enrollment-1')
  await self.message('confirm')
  self.client.get_checkout.return_value={'id':'checkout-1','status':'FAILED'}
  await self.reel()
  self.assertEqual(store.get(self.uid)['phase'],'products')
  self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_pending_checkout_still_blocks_next_reel(self):
  await self.quote();self.client.get_enrollment.return_value={'status':'ACTIVE'};state.update_user(self.uid,enrollment_id='enrollment-1')
  await self.message('confirm')
  self.client.get_checkout.return_value={'id':'checkout-1','status':'REQUIRES_ACTION'}
  await self.reel()
  self.assertEqual(store.get(self.uid)['phase'],'payment')
  self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_bad_attachment_cannot_fetch_internal_urls(self):
  from app.media.instagram import trusted_media
  for url in ('http://lookaside.fbsbx.com/ig_messaging_cdn/','https://127.0.0.1/','https://lookaside.fbsbx.com.evil.test/ig_messaging_cdn/','https://lookaside.fbsbx.com/other/'):
   self.assertFalse(trusted_media(url))

if __name__=='__main__':unittest.main()
