"""Anthropic commerce core over Reap, driven by the existing OpenAI model.

The optional chat path uses upstream contracts, skill loader, prompt and executor.
Payment stays in the existing explicit Telegram checkout flow.
"""
import asyncio
import hashlib
import json
from pathlib import Path

from commerce_common.skills import SkillRegistry
from shopping_agent import (
    Cart, NotOffered, Product, ProductDetails, ShoppingAgentConfig,
    ShoppingSessionContext, ShoppingSessionState, StorefrontBackend, UserPreferences,
)
from shopping_agent.executor import ShoppingToolExecutor
from shopping_agent.fencing import STOREFRONT_FENCE
from shopping_agent.prompt import build_static_system
from shopping_agent.tools.registry import build_tools

from app.agent.conversation import read_context, write_context
from app.agent.profile import load_profile
from app.agent.recognize import _openai
from app.agent.search import _to_candidate
from app.config import settings
from app.models import ProductCandidate
from app.purchase.budget import get_budget
from app.purchase.service import client

SKILLS = Path(__file__).resolve().parents[2] / 'third_party/commerce-agents/shopping-agent/skills'
READ_TOOLS = {'load_skill', 'search_products', 'get_product_details', 'get_preferences',
              'present_products', 'present_comparison', 'present_plan', 'present_guide'}
RULES = '''Telegram instructions: answer the latest message using the retained Reel evidence.
Product matching already happened. Do not repeat video analysis. Keep answers short.
Use search_products for new product recommendations, and get_product_details before claiming
specific compatibility or product features. Never set min_price or max_price unless the user
provided a numeric price boundary. Affordable or cheaper means sort price_asc, not a zero ceiling.
Use present_products for purchasable recommendations.
No cart, payment, order, policy, or shipping systems are available here. Use existing Buy buttons
for purchase approval. Never claim to have ordered anything or prepared a payable basket.
Only explicit profile entries are known possessions; unknown means unknown, not absent.
Do not invent recipe ingredients or exact cooking conversions. Ask for the recipe if evidence
is missing. Do not treat having an oven as having a suitable dish or blender.
Never include numeric product prices in generated prose: canonical cards show catalog prices.
Give one best pick and at most two alternatives, or up to three distinct ingredients.
If the customer only wants advice, answer without unnecessary catalog calls.
Do not discuss demo profiles or demo context. No em dashes.
Do not write memory: pantry updates are handled separately with confirmation.
These Telegram limits override any generic skill's cart or checkout instructions.'''


def product(candidate: ProductCandidate) -> Product:
    return Product(product_id=candidate.product_id, title=candidate.name,
                   price=candidate.price_min, currency=candidate.currency,
                   image_url=candidate.image_url,
                   attributes={'merchant': candidate.merchant, 'price_basis': 'lowest listed variant; shipping excluded'})


class ReapStorefront(StorefrontBackend):
    """Read-only storefront adapter; unsupported systems are disabled in config."""
    def __init__(self, uid: str):
        self.uid = uid
        self.candidates: dict[str, ProductCandidate] = {}
        self.trace: list[str] = []
        for raw in read_context(uid).get('reel', {}).get('products', []):
            c = ProductCandidate.model_validate(raw)
            self.candidates[c.product_id] = c

    def check(self, session):
        if session.user_id != self.uid:
            raise ValueError('Session mismatch')

    async def search_products(self, session, query, filters=None, limit=8):
        self.check(session)
        self.trace.append('search_products')
        data = await client().search_products(query, limit=8)
        candidates = [_to_candidate(p) for p in data.get('products', []) if p.get('available', True)]
        budget = get_budget(self.uid)
        ceiling = filters.max_price if filters else None
        if budget and budget[1] == settings.reap_default_currency:
            ceiling = min(ceiling, budget[0]) if ceiling is not None else budget[0]
        if ceiling is not None:
            candidates = [c for c in candidates if c.price_min <= ceiling]
        if filters and filters.min_price is not None:
            candidates = [c for c in candidates if c.price_min >= filters.min_price]
        if filters and filters.sort in ('price_asc', 'price_desc'):
            candidates.sort(key=lambda c: c.price_min, reverse=filters.sort == 'price_desc')
        # Reap's supported filters are narrower than the blueprint's. Do not silently
        # pretend ratings or arbitrary attributes were verified.
        if filters and (filters.min_rating is not None or filters.attributes or filters.category):
            raise NotOffered('Verified rating, category and attribute filters')
        self.candidates.update({c.product_id: c for c in candidates})
        return [product(c) for c in candidates[:limit]]

    async def get_product_details(self, session, product_id):
        self.check(session)
        self.trace.append('get_product_details')
        data = await client().product_details([product_id])
        raw = next((p for p in data.get('products', []) if p.get('id') == product_id), None)
        if raw is None:
            return None
        c = _to_candidate(raw) if raw.get('priceRange') else self.candidates.get(product_id)
        if c is None:
            raise NotOffered('A verified catalog price for this product')
        self.candidates[c.product_id] = c
        return ProductDetails(**product(c).model_dump(),
                              long_description=str(raw.get('description') or '')[:4000])

    async def get_preferences(self, session):
        self.check(session)
        self.trace.append('get_preferences')
        p = load_profile(self.uid)
        return UserPreferences(user_id=self.uid, preferences={
            key: json.dumps(p.get(key, [])) for key in ('home', 'not_owned', 'pantry', 'likes', 'dislikes', 'sizes', 'inventory_facts')})

    async def get_cart(self, session):
        self.check(session)
        return Cart(currency=settings.reap_default_currency)

    async def add_to_cart(self, *args, **kwargs):
        raise NotOffered('Chat cart writes')

    async def update_cart_item(self, *args, **kwargs):
        raise NotOffered('Chat cart writes')

    async def remove_from_cart(self, *args, **kwargs):
        raise NotOffered('Chat cart writes')

    async def get_orders(self, *args, **kwargs):
        raise NotOffered('Order lookup')

    async def get_order(self, *args, **kwargs):
        raise NotOffered('Order lookup')

    async def search_policies(self, *args, **kwargs):
        raise NotOffered('Merchant policies')

    async def get_fulfillment_options(self, *args, **kwargs):
        raise NotOffered('Delivery estimates before checkout')


def make_executor(uid: str):
    backend = ReapStorefront(uid)
    config = ShoppingAgentConfig(brand_name='ShopTheReel', model=settings.openai_vision_model,
        enable_cart=False, enable_orders=False, enable_policies=False,
        enable_fulfillment=False, enable_memory=False, max_tool_iterations=4,
        max_search_results=5)
    skills = SkillRegistry.from_dir(SKILLS)
    session = ShoppingSessionContext(session_id=hashlib.sha256(uid.encode()).hexdigest(), user_id=uid, timezone='Asia/Singapore')
    state = ShoppingSessionState()
    state.remember_products([product(c) for c in backend.candidates.values()])
    executor = ShoppingToolExecutor(backend=backend, config=config, skills=skills, session=session, state=state)
    return backend, config, skills, executor


def openai_tools(config, skills):
    tools = []
    for contract in build_tools(config, skills.names):
        if contract['name'] not in READ_TOOLS:
            continue
        schema = contract['input_schema']
        if contract['name'] == 'search_products':
            # Present only the filters our Reap adapter can actually enforce.
            properties = schema['properties']['filters']['properties']
            schema['properties']['filters']['properties'] = {k: v for k, v in properties.items()
                if k in ('min_price', 'max_price', 'sort')}
            schema['properties']['filters']['properties']['sort']['enum'] = ['relevance', 'price_asc', 'price_desc']
        tools.append({'type': 'function', 'function': {'name': contract['name'],
            'description': contract['description'], 'parameters': schema}})
    return tools


def presentation(events, backend):
    """Render upstream enriched events; product identities always come from the backend."""
    lines, cards = [], {}
    for event in events:
        if event.type != 'ui':
            continue
        component, payload = event.data['component'], event.data['payload']
        if payload.get('title'):
            lines.append(payload['title'])
        if component == 'products':
            for item in payload.get('items', []):
                pid = item['product']['product_id']
                if pid in backend.candidates:
                    cards[pid] = backend.candidates[pid]
                    if item.get('reason'):
                        lines.append(f"{backend.candidates[pid].name}: {item['reason']}")
        elif component == 'comparison':
            for entry in payload.get('entries', []):
                pid = entry['product']['product_id']
                if pid in backend.candidates:
                    cards[pid] = backend.candidates[pid]
                    lines.append(f"{backend.candidates[pid].name}: " + '; '.join(entry.get('pros', []) + entry.get('cons', [])))
        elif component == 'plan':
            if payload.get('intro'):
                lines.append(payload['intro'])
            for step in payload.get('steps', []):
                lines.append(step['label'] + (': ' + step['detail'] if step.get('detail') else ''))
                for p in step.get('products', []):
                    if p['product_id'] in backend.candidates:
                        cards[p['product_id']] = backend.candidates[p['product_id']]
        elif component == 'guide':
            for section in payload.get('sections', []):
                lines.append(section['heading'] + ': ' + section['body'])
    return lines, list(cards.values())[:8]


async def _turn(uid: str, text: str) -> dict:
    backend, config, skills, executor = make_executor(uid)
    context = read_context(uid)
    prefs = await executor.execute('get_preferences', {})
    messages = [{'role': 'system', 'content': build_static_system(config, skills) + '\n' + RULES},
                {'role': 'user', 'content': STOREFRONT_FENCE.fence_payload({
                    'preferences': prefs.result_text, 'reel': context.get('reel'),
                    'history': context.get('history', [])[-6:]} )},
                {'role': 'user', 'content': text[:2000]}]
    tools = openai_tools(config, skills)
    events, reply, call_count = [], '', 0
    for iteration in range(config.max_tool_iterations + 1):
        response = await _openai().chat.completions.create(model=settings.openai_vision_model,
            temperature=0, messages=messages, tools=tools,
            tool_choice='none' if iteration == config.max_tool_iterations else 'auto', max_tokens=1800)
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True, exclude={'refusal', 'annotations', 'audio'}))
        if not message.tool_calls:
            reply = message.content or ''
            break
        for call in message.tool_calls:
            call_count += 1
            if call.function.name not in READ_TOOLS or call_count > 12:
                result_text = 'This tool is unavailable. Answer using existing evidence.'
            else:
                try:
                    arguments = json.loads(call.function.arguments)
                except ValueError:
                    arguments = {}
                outcome = await executor.execute(call.function.name, arguments)
                events.extend(outcome.events)
                result_text = outcome.result_text
            messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': result_text})
    lines, cards = presentation(events, backend)
    rendered = '\n'.join(([reply] if reply else []) + lines).replace('—', ',')[:3500]
    if not rendered:
        rendered = 'What would you like to know about the product or recipe?'
    latest = read_context(uid)
    latest['history'] = (latest.get('history', []) + [{'user': text[:2000], 'assistant': rendered}])[-8:]
    write_context(uid, latest)
    return {'reply': rendered, 'cards': cards, 'trace': backend.trace}


async def chat(uid: str, text: str) -> dict:
    try:
        async with asyncio.timeout(90):
            return await _turn(uid, text)
    except Exception:
        return {'reply': 'I could not finish that comparison right now. Your product and Buy buttons still work. Please try again.', 'cards': []}
