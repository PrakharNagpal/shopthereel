import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.agent import profile
from app.agent.personalize import mock_air_fryer_scene
from app.agent.search import recognize_and_search
from app.dm import render, router
from app.models import ProductCandidate, RecognitionResult


class ProfileTests(unittest.TestCase):
    def test_profile_does_not_leak_to_other_chats(self):
        with patch.object(profile.settings, "front_door", "telegram"), patch.object(profile.settings, "telegram_allowed_chat_ids", "demo"):
            self.assertEqual(profile.load_profile("stranger"), {})
            self.assertEqual(profile.load_profile("demo")["sizes"], {})

    def test_edit_persists_and_removes_contradictory_ownership(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(profile.settings, "front_door", "telegram"), patch.object(profile.settings, "telegram_allowed_chat_ids", "demo"), patch.object(profile, "_path", return_value=Path(directory) / "profile.json"):
            profile.update_profile("demo", "home", "oven, air fryer")
            p = profile.load_profile("demo")
            self.assertNotIn("air fryer", p["not_owned"])
            profile.update_profile("demo", "likes", "secondhand")
            self.assertNotIn("likes", profile.load_profile("demo")["sample_fields"])

    def test_appliance_ownership_keeps_accessories(self):
        p = {"home": ["oven"]}
        self.assertTrue(profile.excluded("Countertop oven", p))
        self.assertFalse(profile.excluded("Oven-safe baking dish", p))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_advice_cannot_replace_closest_match(self):
        bundle, detected = mock_air_fryer_scene()
        candidates = [ProductCandidate(product_id=str(i), name=f"Air fryer {i}", merchant="store", price_min=100, price_max=100, currency="SGD") for i in range(2)]
        result = RecognitionResult(detected=detected, match_type="similar", candidates=candidates)
        with patch.object(router, "advise", AsyncMock(return_value={"recommended_indices": [999, 1, 1, -1], "note": "Value pick"})), patch.dict(router._personal_advice, {}, clear=True):
            await router.add_personal_advice("demo", bundle, result)
            self.assertEqual([c.product_id for c in result.candidates], ["0", "1"])

    async def test_closest_match_is_kept_even_when_owned(self):
        bundle, detected = mock_air_fryer_scene()
        candidate = ProductCandidate(product_id="one", name="Air fryer", merchant="store", price_min=100, price_max=100, currency="SGD")
        cached = {"detected": detected.model_dump(), "ranked": [{"c": candidate.model_dump(), "s": 0.9}], "first_query": {"one": 0}}
        with patch("app.agent.search.state.get_recognition", return_value=cached), patch("app.agent.search.get_budget", return_value=None):
            self.assertEqual(len((await recognize_and_search(bundle, "owner")).candidates), 1)
            self.assertEqual(len((await recognize_and_search(bundle, "other")).candidates), 1)

    async def test_advice_survives_no_catalog_results(self):
        _, detected = mock_air_fryer_scene()
        result = RecognitionResult(detected=detected, match_type="none", candidates=[], note="Use your existing oven.")
        with patch.object(render, "send_text", AsyncMock()) as message:
            await render.results("demo", result)
            self.assertIn("Use your existing oven", message.call_args.args[1])

    async def test_old_recipe_button_cannot_use_new_advice(self):
        with patch.dict(router._personal_advice, {"demo": {"reel_id": "new", "oven_alternative": "new advice"}}, clear=True), patch.object(router, "send_text", AsyncMock()) as message:
            await router.oven_alternative("demo", "old")
            self.assertNotEqual(message.call_args.args[1], "new advice")


if __name__ == "__main__":
    unittest.main()
