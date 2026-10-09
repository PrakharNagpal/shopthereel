import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.config import settings
from app.main import app
from app import state
from app.web import store

class WebCheckoutTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.prev=settings.db_path;settings.db_path=self.tmp.name+'/test.db'
  self.token=settings.web_api_token;settings.web_api_token='test-only-token'
  self.headers={'x-commerce-token':'test-only-token','x-commerce-session':'web-test-owner'}
  self.c=TestClient(app)
  self.reap=AsyncMock()
  self.reap.get_enrollment.return_value={'status':'ACTIVE'}
  self.reap.create_checkout.return_value={'id':'checkout-test','status':'REQUIRES_ACTION','nextAction':{'url':'https://sandbox.example/approve'},'amount':{'amount':44.9,'currency':'SGD'}}
  self.reap.get_checkout.return_value={'id':'checkout-test','status':'COMPLETED','orderId':'order-test','finalAmount':{'amount':44.9,'currency':'SGD'}}
  self.mock=patch('app.purchase.service.client',return_value=self.reap);self.mock.start()
  state.update_user('web-test-owner',enrollment_id='enrollment-test',pending_quote_id='quote-test')
  store.save_quote('web-test-owner',{'id':'quote-test','amount':44.9,'currency':'SGD','expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()})
 def tearDown(self):
  self.mock.stop();settings.db_path=self.prev;settings.web_api_token=self.token;self.tmp.cleanup()
 def pay(self,uid=None):
  return self.c.post('/web/checkout',headers=self.headers if uid is None else {**self.headers,'x-commerce-session':uid},json={'quote_id':'quote-test','confirmed':True})
 def test_full_checkout_approval_poll_and_duplicate(self):
  r=self.pay();self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'REQUIRES_ACTION')
  r=self.c.get('/web/checkout/checkout-test',headers=self.headers);self.assertEqual(r.json()['order_id'],'order-test');self.assertEqual(state.orders_today('web-test-owner'),1)
  r=self.pay();self.assertEqual(r.json()['status'],'COMPLETED');self.assertEqual(self.reap.create_checkout.await_count,1)
  self.assertEqual(self.reap.create_checkout.call_args.kwargs['idempotency_key'],'web-quote-test')
 def test_budget_is_rechecked_before_checkout(self):
  state.update_user('web-test-owner',budget_per_order=10,budget_currency='SGD');self.assertEqual(self.pay().status_code,409);self.reap.create_checkout.assert_not_awaited()
 def test_currency_mismatch_blocks_checkout(self):
  store.save_quote('web-test-owner',{'id':'quote-test','amount':44.9,'currency':'USD','expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()});self.assertEqual(self.pay().status_code,409);self.reap.create_checkout.assert_not_awaited()
 def test_expired_quote_requires_new_approval(self):
  store.save_quote('web-test-owner',{'id':'quote-test','amount':44.9,'currency':'SGD','expiresAt':'2020-01-01T00:00:00Z'});self.assertEqual(self.pay().status_code,409);self.reap.create_checkout.assert_not_awaited()
 def test_newer_quote_invalidates_old_quote(self):
  state.update_user('web-test-owner',pending_quote_id='newer');self.assertEqual(self.pay().status_code,409)
 def test_quote_and_order_ownership(self):
  self.assertEqual(self.pay('web-other-owner').status_code,404)
  self.pay();r=self.c.get('/web/checkout/checkout-test',headers={**self.headers,'x-commerce-session':'web-other-owner'});self.assertEqual(r.status_code,404)
 def test_active_enrollment_required(self):
  self.reap.get_enrollment.return_value={'status':'REQUIRES_ACTION'};self.assertEqual(self.pay().status_code,409)
 def test_same_brand_different_model_is_not_exact(self):
  from app.agent.search import _verified
  from app.models import ProductCandidate
  c=ProductCandidate(product_id="x",name="Sony WI-C100 headphones",merchant="Store",price_min=40,price_max=40,currency="SGD")
  self.assertFalse(_verified(c,"Sony",["wi-c200"]))
  self.assertFalse(_verified(c,"Sony",[]))
  self.assertTrue(_verified(c,"Sony",["wi-c100"]))
 def test_internal_token_required(self):
  self.assertEqual(self.c.get('/web/status').status_code,401)
 def test_browser_result_handoff(self):
  result={'detected':{'name':'Headphones','category':'electronics','brand_source':'none','attributes':[],'queries':['headphones'],'best_frame':0,'confidence':0.7},'match_type':'none','candidates':[]}
  r=self.c.post('/web/handoff',headers=self.headers,json={'result':result});self.assertEqual(r.status_code,200,r.text)
  token=r.json()['url'].split('reel=')[1];r=self.c.get('/web/handoff/'+token,headers=self.headers);self.assertEqual(r.json()['detected']['name'],'Headphones')

if __name__=='__main__':unittest.main()
