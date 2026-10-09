import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.agent import profile, conversation
from app.dm import router
from app.meta.parse import InboundEvent


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for patcher in [patch.object(profile.settings, 'front_door', 'telegram'),
                        patch.object(profile.settings, 'telegram_allowed_chat_ids', 'demo'),
                        patch.object(profile, '_path', return_value=Path(self.directory.name) / 'profile.json'),
                        patch.object(conversation, 'context_path', return_value=Path(self.directory.name) / 'context.json')]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_sample_unknown_confirmed_and_absent_are_distinct(self):
        self.assertIn('sample', conversation.inventory_answer('demo', 'salt', 'pantry'))
        self.assertIn('do not know', conversation.inventory_answer('demo', 'basil', 'pantry'))
        conversation.record_inventory('demo', 'basil', 'pantry', True)
        self.assertIn('lists basil', conversation.inventory_answer('demo', 'basil', 'pantry'))
        self.assertIn('sample', conversation.inventory_answer('demo', 'salt', 'pantry'))
        self.assertIn('basil', conversation.inventory_answer('demo', 'herbs', 'pantry'))
        conversation.record_inventory('demo', 'basil', 'pantry', False)
        self.assertIn('do not currently have basil', conversation.inventory_answer('demo', 'basil', 'pantry'))

    def test_inventory_survives_reload_and_cannot_leak(self):
        conversation.record_inventory('demo', 'blender', 'home', True)
        self.assertIn('blender', profile.load_profile('demo')['home'])
        self.assertEqual(profile.load_profile('stranger'), {})
        conversation.write_context('demo', {'history': ['one']})
        self.assertEqual(conversation.read_context('demo')['history'], ['one'])
        self.assertEqual(conversation.read_context('stranger'), {})

    async def test_card_text_does_not_reach_model_or_storage(self):
        with patch.object(conversation, '_openai') as client:
            reply = await conversation.respond('demo', 'my card is 4111 1111 1111 1111')
            client.assert_not_called()
            self.assertIn('secure payment', reply['reply'])
            self.assertEqual(conversation.read_context('demo'), {})

    async def test_stale_inventory_button_cannot_confirm_new_update(self):
        conversation.write_context('demo', {'pending_inventory': {'item': 'basil', 'field': 'pantry', 'present': True, 'nonce': 'new'}})
        with patch.object(router, 'send_text', AsyncMock()):
            await router.handle_payload_tap(InboundEvent(igsid='demo', kind='postback', payload='INVENTORY:yes:old'))
        self.assertNotIn('basil', profile.load_profile('demo')['pantry'])
        self.assertEqual(conversation.read_context('demo')['pending_inventory']['nonce'], 'new')


if __name__ == '__main__':
    unittest.main()
