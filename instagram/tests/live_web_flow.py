"""Real OpenAI + Reap test, without a live charge or invented enrollment status."""
import asyncio,json
from pathlib import Path
import httpx

async def run():
 async with httpx.AsyncClient(base_url='http://localhost:3102/api/commerce/',timeout=240) as c:
  s=await c.get('status');assert s.status_code==200 and s.json()['sandbox'];print('PASS connected sandbox')
  with Path('work/test-product-reel.mp4').open('rb') as f:
   r=await c.post('analyze',files={'media':('product-reel.mp4',f,'video/mp4')})
  assert r.status_code==200,r.text
  a=r.json();assert a['evidence']['frames']>0;assert a['candidates'],a
  print('PASS video frames + OpenAI recognition + Reap search:',a['detected']['name'],len(a['candidates']),'candidates')
  Path('work/test-recognition.json').write_text(json.dumps(a))
  p=a['candidates'][0];d=(await c.get('products/'+p['product_id'])).json()
  opts=[next(v['optionId'] for v in g['values'] if v.get('available',True)) for g in d['options']]
  r=await c.post('quote',json={'product_id':p['product_id'],'option_ids':opts});assert r.status_code==200,r.text
  q=r.json();assert q['final_amount']>0;print('PASS variants and final quote:',q['currency'],q['final_amount'])
  r=await c.post('checkout',json={'quote_id':q['quote_id'],'confirmed':False});assert r.status_code==400;print('PASS payment requires explicit approval')
  r=await c.post('checkout',json={'quote_id':q['quote_id'],'confirmed':True});assert r.status_code==409;print('PASS unenrolled card blocks checkout')
  r=await c.post('enrollment',json={});assert r.status_code==200,r.text
  e=r.json();assert e['url'].startswith('https://');print('PASS real Reap hosted card-enrollment page')
  Path('work/test-enrollment.json').write_text(json.dumps(e));Path('work/test-quote.json').write_text(json.dumps(q));Path('work/test-cookies.json').write_text(json.dumps(dict(c.cookies)))
  async with httpx.AsyncClient(base_url='http://localhost:3102/api/commerce/',timeout=40) as other:
   await other.get('status');r=await other.post('checkout',json={'quote_id':q['quote_id'],'confirmed':True});assert r.status_code==404;print('PASS quote ownership isolates sessions')
  r=await c.post('analyze',data={'url':'http://127.0.0.1/private'});assert r.status_code==400;print('PASS invalid source URL rejected')
asyncio.run(run())
