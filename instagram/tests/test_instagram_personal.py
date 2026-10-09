import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import test_instagram_chat as fixture
from app import state
from app.agent import profile,conversation
from app.agent.personalize import mock_air_fryer_scene
from app.dm import instagram as ig,instagram_personal as personal,instagram_store as store
from app.models import RecognitionResult,ProductCandidate

class PersonalTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  await fixture.InstagramChatTests.asyncSetUp(self)
  p=patch.object(personal.personalize,'advise',new=AsyncMock(return_value={}))
  p.start();self.patches.append(p)
 asyncTearDown=fixture.InstagramChatTests.asyncTearDown
 message=fixture.InstagramChatTests.message
 quote=fixture.InstagramChatTests.quote
 reel=fixture.InstagramChatTests.reel
 choice=fixture.InstagramChatTests.choice
 def model(self,action):
  client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))])))))
  return client
 def test_new_profile_is_empty_and_never_reads_telegram_seed(self):
  p=profile.load_profile(self.uid);self.assertEqual(p['home'],[]);self.assertEqual(p['pantry'],[]);self.assertEqual(p['sizes'],{})
  self.assertEqual(profile.load_profile('telegram-user'),{})
 def test_inventory_is_persisted_scoped_and_distinguishes_unknown_from_absent(self):
  self.assertIn('do not know',conversation.inventory_answer(self.uid,'basil','pantry'))
  conversation.record_inventory(self.uid,'basil','pantry',True)
  self.assertIn('lists basil',conversation.inventory_answer(self.uid,'basil','pantry'))
  self.assertEqual(profile.load_profile(ig.owner('other'))['pantry'],[])
  conversation.record_inventory(self.uid,'basil','pantry',False)
  self.assertIn('do not currently have',conversation.inventory_answer(self.uid,'basil','pantry'))
 def test_explicit_profile_edit_resolves_ownership_conflict(self):
  profile.update_profile(self.uid,'not_owned','air fryer');profile.update_profile(self.uid,'home','oven, air fryer')
  self.assertEqual(profile.load_profile(self.uid)['not_owned'],[])
  self.assertTrue(profile.excluded('Countertop oven',profile.load_profile(self.uid)))
  self.assertFalse(profile.excluded('Oven-safe baking dish',profile.load_profile(self.uid)))
 async def test_card_or_secret_never_reaches_model_or_profile(self):
  with patch.object(conversation,'_openai') as model:
   await self.message('my card is 4111 1111 1111 1111');model.assert_not_called()
  with self.assertRaises(ValueError):profile.update_profile(self.uid,'background','my otp is 123456')
  self.assertEqual(conversation.read_context(self.uid),{})
 async def test_memory_yes_is_not_purchase_confirmation(self):
  await self.quote()
  answer={'intent':'remember','item':'basil','field':'pantry','present':True,'reply':'','query':''}
  with patch.object(conversation,'_openai',return_value=self.model(answer)):
   await self.message('I have basil')
  self.assertEqual(profile.load_profile(self.uid)['pantry'],[])
  await self.message('yes');self.assertIn('basil',profile.load_profile(self.uid)['pantry'])
  self.client.create_checkout.assert_not_awaited()
 async def test_old_memory_button_cannot_save_new_update(self):
  await self.reel();s=store.get(self.uid)
  conversation.write_context(self.uid,{'pending_inventory':{'item':'basil','field':'pantry','present':True,'nonce':'new'}})
  await self.message(payload=ig.payload(self.uid,s,'INVENTORY',{'nonce':'old','yes':True}))
  self.assertEqual(profile.load_profile(self.uid)['pantry'],[])
 async def test_profile_clear_removes_reel_and_memory_only_for_owner(self):
  conversation.record_inventory(self.uid,'oven','home',True);conversation.write_context(self.uid,{'history':['one']})
  conversation.record_inventory(ig.owner('other'),'basil','pantry',True)
  await self.message('profile clear');self.assertEqual(profile.load_profile(self.uid)['home'],[]);self.assertEqual(conversation.read_context(self.uid),{})
  self.assertEqual(profile.load_profile(ig.owner('other'))['pantry'],['basil'])
 async def test_spending_menu_custom_daily_value_and_pause(self):
  await self.message('settings');await self.message(payload=self.choice('RULE'))
  await self.message('25');self.assertEqual(state.get_user(self.uid)['budget_per_order'],25)
  s=store.get(self.uid);await ig.action(self.sender,s,'RULE','daily');await self.message('2.5')
  self.assertIsNone(state.get_user(self.uid).get('max_orders_per_day'))
  await self.message('2');self.assertEqual(state.get_user(self.uid)['max_orders_per_day'],2)
  await self.message('pause buying');await self.quote();await self.message('confirm');self.client.create_checkout.assert_not_awaited()
 async def test_rule_menu_restores_pending_variant_choices(self):
  await self.reel();await self.message('1');await self.message('settings');await self.message(payload=self.choice('RULE_DONE'));await self.message('black')
  self.assertEqual(store.get(self.uid)['phase'],'quote')
 async def test_memory_confirmation_restores_pending_variant_choices(self):
  await self.reel();await self.message('1')
  answer={'intent':'remember','item':'basil','field':'pantry','present':True,'reply':'','query':''}
  with patch.object(conversation,'_openai',return_value=self.model(answer)):await self.message('I have basil')
  await self.message('yes');await self.message('black');self.assertEqual(store.get(self.uid)['phase'],'quote')
 async def test_extra_confirmation_cannot_be_bypassed(self):
  state.update_user(self.uid,confirm_above=20,enrollment_id='enrollment-1');self.client.get_enrollment.return_value={'status':'ACTIVE'}
  await self.quote();await self.message('confirm');self.assertEqual(store.get(self.uid)['phase'],'extra_confirm');self.client.create_checkout.assert_not_awaited()
  await self.message(payload=self.choice('CONFIRM_EXTRA'));self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_recipe_advice_survives_no_catalog_items_and_stale_button(self):
  profile.update_profile(self.uid,'home','oven');bundle,detected=mock_air_fryer_scene();result=RecognitionResult(detected=detected,match_type='none',candidates=[])
  advice={'note':'You can use your oven. Exact recipe needed for timing.','oven_alternative':'Use a suitable oven-safe dish; share the recipe for timing.','alternative_queries':[],'recommended_indices':[999,-1]}
  with patch.object(personal.personalize,'advise',new=AsyncMock(return_value=advice)):
   await personal.enrich(self.sender,bundle,result)
  self.assertTrue(any('Exact recipe needed' in m[2] for m in self.messages if m[0]=='text'))
  s=store.get(self.uid);await ig.action(self.sender,s,'OVEN',bundle.reel_id)
  with self.assertRaises(Exception):await ig.action(self.sender,s,'OVEN','older-reel')
 async def test_personal_ranking_uses_only_real_candidates(self):
  profile.update_profile(self.uid,'likes','value');bundle,detected=mock_air_fryer_scene()
  cands=[ProductCandidate(product_id=str(i),name='Air fryer',merchant='store',price_min=100,price_max=100,currency='SGD') for i in range(2)]
  result=RecognitionResult(detected=detected,match_type='similar',candidates=cands)
  with patch.object(personal.personalize,'advise',new=AsyncMock(return_value={'recommended_indices':[999,1,1,-1],'note':'Value pick'})):
   await personal.enrich(self.sender,bundle,result)
  self.assertEqual([c.product_id for c in result.candidates],['1','0'])
 async def test_saved_size_never_skips_variant_choice(self):
  profile.update_profile(self.uid,'sizes','shirt=M')
  self.client.product_details.return_value={'products':[{'id':'product-1','name':'Shirt','options':[{'name':'Size','values':[{'label':'M','optionId':'m','available':True},{'label':'L','optionId':'l','available':True}]}],'defaultVariant':{'id':'m'}}]}
  await self.reel();await self.message('1')
  self.assertEqual(store.get(self.uid)['phase'],'options');self.client.create_quote.assert_not_awaited()
 async def test_cached_ranking_is_filtered_for_each_owner_separately(self):
  from app.agent.search import recognize_and_search
  bundle,detected=mock_air_fryer_scene();candidate=ProductCandidate(product_id='air-fryer',name='Compact air fryer',merchant='store',price_min=100,price_max=100,currency='SGD')
  cached={'detected':detected.model_dump(),'ranked':[{'c':candidate.model_dump(),'s':.9}],'first_query':{'air-fryer':0}}
  profile.update_profile(self.uid,'home','air fryer')
  with patch('app.agent.search.state.get_recognition',return_value=cached):
   self.assertEqual((await recognize_and_search(bundle,self.uid)).candidates,[])
   self.assertEqual(len((await recognize_and_search(bundle,ig.owner('other'))).candidates),1)
 async def test_addons_require_completed_order_and_never_purchase_automatically(self):
  await self.quote();state.update_user(self.uid,enrollment_id='enrollment-1');self.client.get_enrollment.return_value={'status':'ACTIVE'};await self.message('confirm');await ig.watch(self.sender,'checkout-1')
  addon=ProductCandidate(product_id='case',name='Headphone storage case',merchant='store',price_min=10,price_max=10,currency='SGD')
  with patch.object(personal.recommend,'suggest_addons',new=AsyncMock(return_value=[addon])):
   await self.message('addons')
  self.assertEqual(store.get(self.uid)['candidates'][0]['product_id'],'case');self.assertEqual(self.client.create_checkout.await_count,1)
 async def test_search_during_payment_cannot_replace_checkout(self):
  await self.quote();state.update_user(self.uid,enrollment_id='enrollment-1');self.client.get_enrollment.return_value={'status':'ACTIVE'};await self.message('confirm')
  await self.message('search something cheaper');self.assertEqual(store.get(self.uid)['checkout'],'checkout-1');self.assertEqual(store.get(self.uid)['phase'],'payment')

if __name__=='__main__':unittest.main()
