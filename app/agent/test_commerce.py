import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent import commerce, conversation, profile
from app.dm import router
from app.meta.parse import InboundEvent
from app.agent.personalize import mock_air_fryer_scene
from app.models import ProductCandidate, RecognitionResult


class CommerceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in [patch.object(profile.settings, 'front_door', 'telegram'),
                        patch.object(profile.settings, 'telegram_allowed_chat_ids', 'demo'),
                        patch.object(profile, '_path', return_value=Path(self.tmp.name)/'profile.json'),
                        patch.object(conversation, 'context_path', return_value=Path(self.tmp.name)/'context.json')]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_legacy_sample_profile_does_not_become_real_inventory(self):
        raw = {'pantry': ['salt', 'basil'], 'background': 'Sample shopper', 'likes': ['value'],
               'sample_fields': ['pantry', 'background', 'likes'], 'inventory_facts': {'pantry': {'basil': True}}}
        clean = profile.clean_profile(raw)
        self.assertEqual(clean['pantry'], ['basil'])
        self.assertEqual(clean['background'], '')
        self.assertEqual(clean['likes'], [])
        self.assertNotIn('demo', profile.describe_profile('demo').lower())

    async def test_upstream_executor_blocks_unseen_products_and_checkout(self):
        backend, config, skills, executor = commerce.make_executor('demo')
        outcome = await executor.execute('present_products', {'picks': [{'product_id': 'invented'}]})
        self.assertTrue(outcome.refused)
        self.assertEqual(outcome.events, [])
        for tool in ('checkout', 'add_to_cart', 'get_orders'):
            self.assertTrue((await executor.execute(tool, {'product_id': 'invented'})).refused)

    async def test_real_core_search_and_presentation_use_catalog_price(self):
        backend, config, skills, executor = commerce.make_executor('demo')
        response = {'products': [{'id': 'one', 'name': 'Rolled oats', 'merchant': {'name': 'Grocer'},
                    'priceRange': {'min': {'amount': 8.5, 'currency': 'SGD'}}}]}
        fake = SimpleNamespace(search_products=AsyncMock(return_value=response))
        with patch.object(commerce, 'client', return_value=fake), patch.object(commerce, 'get_budget', return_value=None):
            await executor.execute('search_products', {'query': 'rolled oats'})
            outcome = await executor.execute('present_products', {'picks': [{'product_id': 'one', 'reason': 'Recipe ingredient'}]})
        self.assertFalse(outcome.refused)
        lines, cards = commerce.presentation(outcome.events, backend)
        self.assertEqual(cards[0].price_min, 8.5)
        self.assertEqual(cards[0].merchant, 'Grocer')
        self.assertIn('Recipe ingredient', '\n'.join(lines))

    async def test_price_filter_checks_more_than_the_first_expensive_result(self):
        backend, config, skills, executor = commerce.make_executor('demo')
        raw = lambda pid, price: {'id': pid, 'name': 'Rolled oats', 'merchant': {'name': 'Grocer'},
              'priceRange': {'min': {'amount': price, 'currency': 'SGD'}}}
        fake = SimpleNamespace(search_products=AsyncMock(return_value={'products': [raw('expensive', 20), raw('affordable', 5)]}))
        with patch.object(commerce, 'client', return_value=fake), patch.object(commerce, 'get_budget', return_value=None):
            outcome = await executor.execute('search_products', {'query': 'rolled oats', 'limit': 1, 'filters': {'max_price': 10}})
        self.assertIn('affordable', outcome.result_text)
        self.assertNotIn('expensive', outcome.result_text)
        fake.search_products.assert_awaited_once_with('rolled oats', limit=8)

    async def test_product_cards_are_sent_before_personalization(self):
        bundle, detected = mock_air_fryer_scene()
        result = RecognitionResult(detected=detected, match_type='similar', candidates=[])
        order = []
        async def rendered(*args):
            order.append('cards')
        def spawned(coro):
            order.append('personal_advice')
            coro.close()
        with patch.object(router, 'bundle_from_url', AsyncMock(return_value=bundle)), patch.object(router, 'recognize_and_search', AsyncMock(return_value=result)), patch.object(router.render, 'results', side_effect=rendered), patch.object(router, 'send_quick_replies', AsyncMock()), patch.object(router, 'spawn', side_effect=spawned), patch.object(router.settings, 'reap_api_key', 'test'), patch.object(router.settings, 'reap_version', 'test'):
            await router.process_reel(InboundEvent(igsid='demo', kind='reel', reel_url='https://instagram.com/reel/test'), None)
        self.assertEqual(order, ['cards', 'personal_advice'])

    async def test_stale_chat_button_does_not_enable_new_reel(self):
        conversation.write_context('demo', {'reel': {'reel_id': 'new'}, 'chat_more': False})
        with patch.object(router, 'send_text', AsyncMock()):
            await router.handle_payload_tap(InboundEvent(igsid='demo', kind='postback', payload='CHAT:old'))
        self.assertFalse(conversation.read_context('demo')['chat_more'])


if __name__ == '__main__':
    unittest.main()
