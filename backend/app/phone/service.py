import json
import re
import uuid
from typing import Any, Dict

from app.core.config import Settings
from app.phone.store import JSONPhoneCallStore


E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class PhoneConfigurationError(RuntimeError):
    pass


class PhoneService:
    """Core-owned control plane for LiveKit rooms and persisted call state."""

    def __init__(self, settings: Settings, store: JSONPhoneCallStore) -> None:
        self.settings = settings
        self.store = store

    def status(self) -> Dict[str, Any]:
        credentials_ready = all(
            (
                self.settings.livekit_url,
                self.settings.livekit_api_key,
                self.settings.livekit_api_secret,
                self.settings.api_token,
                self.settings.phone_worker_token and len(self.settings.phone_worker_token) >= 32,
                self.settings.phone_tts_voice,
            )
        )
        return {
            "enabled": self.settings.phone_enabled,
            "configured": credentials_ready,
            "outbound_enabled": self.settings.outbound_calls_enabled,
            "outbound_configured": bool(self.settings.livekit_sip_outbound_trunk_id),
            "agent_name": self.settings.phone_agent_name,
            "sip_provider": "verimor",
            "codecs": ["PCMA", "PCMU"],
            "sms": "disabled",
        }

    def _require_livekit(self) -> None:
        if not self.settings.phone_enabled:
            raise PhoneConfigurationError("Phone integration is disabled.")
        if not all((self.settings.livekit_url, self.settings.livekit_api_key, self.settings.livekit_api_secret)):
            raise PhoneConfigurationError("LiveKit credentials are incomplete.")

    @staticmethod
    def _livekit_api() -> Any:
        try:
            from livekit import api
        except ImportError as exc:
            raise PhoneConfigurationError(
                "Phone integration requires the optional LiveKit dependencies."
            ) from exc
        return api

    def _api(self) -> Any:
        self._require_livekit()
        api = self._livekit_api()
        return api.LiveKitAPI(
            url=self.settings.livekit_url,
            api_key=self.settings.livekit_api_key,
            api_secret=self.settings.livekit_api_secret,
        )

    async def hangup(self, call_id: str) -> Dict[str, Any]:
        item = self.store.get(call_id)
        if item is None:
            raise KeyError("Phone call was not found.")
        room_name = str(item.get("room_name") or "")
        if not room_name:
            raise PhoneConfigurationError("Call has no LiveKit room assignment.")
        client = self._api()
        api = self._livekit_api()
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
        finally:
            await client.aclose()
        return self.store.update(call_id, "ended", result="hung_up_by_operator")

    async def start_outbound(self, destination: str) -> Dict[str, Any]:
        self._require_livekit()
        if not self.settings.outbound_calls_enabled:
            raise PermissionError("Outbound calls are disabled by server policy.")
        if not self.settings.livekit_sip_outbound_trunk_id:
            raise PhoneConfigurationError("LIVEKIT_SIP_OUTBOUND_TRUNK_ID is not configured.")
        if not E164.fullmatch(destination):
            raise ValueError("Destination must use E.164 format, for example +905551112233.")

        call_id = str(uuid.uuid4())
        room_name = f"akashi-phone-{call_id}"
        item = self.store.update(
            call_id,
            "ringing",
            direction="outbound",
            room_name=room_name,
            caller_number=self.settings.verimor_sip_username or "AKASHI",
            callee_number=destination,
        )
        client = self._api()
        api = self._livekit_api()
        try:
            await client.room.create_room(
                api.CreateRoomRequest(name=room_name, empty_timeout=60, departure_timeout=30)
            )
            await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self.settings.phone_agent_name,
                    room=room_name,
                    metadata=json.dumps(
                        {"call_id": call_id, "direction": "outbound", "destination": destination}
                    ),
                )
            )
            await client.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=self.settings.livekit_sip_outbound_trunk_id,
                    sip_call_to=destination,
                    room_name=room_name,
                    participant_identity=f"sip-{call_id}",
                    participant_name=destination,
                    participant_attributes={
                        "akashi.call.id": call_id,
                        "akashi.call.direction": "outbound",
                    },
                    media=api.SIPMediaConfig(
                        only_listed_codecs=True,
                        codecs=[api.SIPCodec(name="PCMA"), api.SIPCodec(name="PCMU")],
                    ),
                    wait_until_answered=False,
                )
            )
            return item
        except Exception as exc:
            self.store.update(
                call_id,
                "failed",
                direction="outbound",
                room_name=room_name,
                callee_number=destination,
                error=f"LiveKit outbound setup failed: {type(exc).__name__}",
            )
            raise
        finally:
            await client.aclose()

