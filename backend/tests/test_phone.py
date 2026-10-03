import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.absolute import AkashiCore, get_core
from app.core.config import Settings
from app.main import app
from app.phone.service import PhoneService
from app.phone.store import JSONPhoneCallStore


API_TOKEN = "phone-api-test-token-000000000000000"
WORKER_TOKEN = "phone-worker-test-token-0000000000000"


class PhoneIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.settings = Settings(
            ai_provider="mock",
            api_token=API_TOKEN,
            memory_file=root / "memory.json",
            long_term_memory_file=root / "long-term.json",
            task_file=root / "tasks.json",
            upload_dir=root / "uploads",
            file_index_file=root / "files.json",
            device_file=root / "devices.json",
            intelligence_file=root / "intelligence.json",
            schedule_file=root / "schedules.json",
            live_state_file=root / "live.json",
            voice_state_file=root / "voice.json",
            phone_calls_file=root / "phone-calls.json",
            phone_enabled=True,
            outbound_calls_enabled=False,
            livekit_url="wss://example.livekit.cloud",
            livekit_api_key="test-key",
            livekit_api_secret="test-secret",
            phone_worker_token=WORKER_TOKEN,
            phone_tts_voice="test-voice",
        )
        self.core = AkashiCore(self.settings)
        app.dependency_overrides[get_core] = lambda: self.core
        self.addCleanup(app.dependency_overrides.clear)
        self.auth_patch = patch("app.core.auth.get_settings", return_value=self.settings)
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {API_TOKEN}"}

    def test_phone_routes_require_user_auth_and_outbound_defaults_off(self) -> None:
        self.assertEqual(self.client.get("/phone/status").status_code, 401)
        status = self.client.get("/phone/status", headers=self.headers)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["configured"])
        self.assertEqual(status.json()["codecs"], ["PCMA", "PCMU"])

        outbound = self.client.post(
            "/phone/outbound",
            headers=self.headers,
            json={"destination": "+905551112233"},
        )
        self.assertEqual(outbound.status_code, 403)

    def test_worker_events_are_separately_authenticated_and_persist_transcript(self) -> None:
        event = {
            "call_id": "call-12345678",
            "state": "connected",
            "caller_number": "+905551112233",
            "room_name": "room-one",
        }
        self.assertEqual(self.client.post("/phone/worker/events", json=event).status_code, 401)
        response = self.client.post(
            "/phone/worker/events",
            headers={"X-Akashi-Phone-Worker-Token": WORKER_TOKEN},
            json=event,
        )
        self.assertEqual(response.status_code, 200)

        transcript = self.client.post(
            "/phone/worker/events",
            headers={"X-Akashi-Phone-Worker-Token": WORKER_TOKEN},
            json={
                **event,
                "state": "caller_speaking",
                "transcript_role": "caller",
                "transcript_text": "Merhaba AKASHI",
            },
        )
        self.assertEqual(transcript.status_code, 200)
        self.assertEqual(transcript.json()["transcript"][0]["content"], "Merhaba AKASHI")

        listing = self.client.get("/phone/calls", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["calls"][0]["caller_number"], "+905551112233")

    def test_store_deduplicates_partial_transcript_and_terminal_state_is_final(self) -> None:
        store = JSONPhoneCallStore(Path(self.temporary.name) / "store.json")
        store.update("call-store", "connected")
        store.update(
            "call-store",
            "caller_speaking",
            transcript_role="caller",
            transcript_text="Merha",
            transcript_final=False,
        )
        store.update(
            "call-store",
            "caller_speaking",
            transcript_role="caller",
            transcript_text="Merhaba",
            transcript_final=True,
        )
        ended = store.update("call-store", "ended", result="completed")
        ignored = store.update("call-store", "connected")
        self.assertEqual(len(ended["transcript"]), 1)
        self.assertEqual(ended["transcript"][0]["content"], "Merhaba")
        self.assertEqual(ignored["state"], "ended")

    def test_hangup_deletes_only_the_assigned_livekit_room(self) -> None:
        store = JSONPhoneCallStore(Path(self.temporary.name) / "hangup.json")
        store.update("call-hangup", "connected", room_name="akashi-call-room")
        service = PhoneService(self.settings, store)
        livekit = MagicMock()
        livekit.room.delete_room = AsyncMock()
        livekit.aclose = AsyncMock()
        with patch.object(service, "_api", return_value=livekit):
            result = asyncio.run(service.hangup("call-hangup"))
        self.assertEqual(result["state"], "ended")
        livekit.room.delete_room.assert_awaited_once()
        livekit.aclose.assert_awaited_once()

    def test_outbound_media_is_restricted_to_verimor_compatible_g711(self) -> None:
        enabled = Settings(
            **{
                **self.settings.__dict__,
                "outbound_calls_enabled": True,
                "livekit_sip_outbound_trunk_id": "ST_test",
            }
        )
        store = JSONPhoneCallStore(Path(self.temporary.name) / "outbound.json")
        service = PhoneService(enabled, store)
        livekit = MagicMock()
        livekit.room.create_room = AsyncMock()
        livekit.agent_dispatch.create_dispatch = AsyncMock()
        livekit.sip.create_sip_participant = AsyncMock()
        livekit.aclose = AsyncMock()
        with patch.object(service, "_api", return_value=livekit):
            asyncio.run(service.start_outbound("+905551112233"))
        request = livekit.sip.create_sip_participant.await_args.args[0]
        self.assertTrue(request.media.only_listed_codecs)
        self.assertEqual([codec.name for codec in request.media.codecs], ["PCMA", "PCMU"])


if __name__ == "__main__":
    unittest.main()
