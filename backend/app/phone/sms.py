from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SMSResult:
    provider_message_id: str
    status: str


class SMSService(ABC):
    """Future Verimor SMS boundary. No active implementation is registered in v1."""

    @abstractmethod
    async def send(self, destination: str, message: str) -> SMSResult:
        raise NotImplementedError


class DisabledSMSService(SMSService):
    async def send(self, destination: str, message: str) -> SMSResult:
        del destination, message
        raise RuntimeError("SMS integration is not enabled.")

