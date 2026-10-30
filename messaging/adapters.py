"""Provider-agnostic SMS adapter interface for messaging.

Core never depends on any external SMS service: it speaks only
this interface, exactly as checkout speaks only its payment
interface. A salon that wants a real SMS provider supplies its
own adapter implementing :class:`SmsAdapter`, and that adapter
lives outside core -- no provider SDK, field, or name appears
here. The one implementation shipped in core needs no provider
at all: a console/no-op adapter for development.
"""
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

DEFAULT_SMS_ADAPTER = "messaging.adapters.ConsoleSmsAdapter"


@dataclass(frozen=True)
class SmsResult:
    """Outcome of an SMS send attempt."""

    success: bool
    status: str
    reference: str = ""
    message: str = ""


class SmsAdapter(ABC):
    """Contract every SMS adapter must implement.

    ``name`` is a short slug identifying the adapter route,
    never a vendor recorded on core data.
    """

    name = ""

    @abstractmethod
    def send_sms(self, to, body):
        """Send ``body`` to phone number ``to``; return an SmsResult."""
        raise NotImplementedError


class ConsoleSmsAdapter(SmsAdapter):
    """Development adapter: logs the message, sends nothing."""

    name = "console"

    def send_sms(self, to, body):
        logger.info("SMS (console, not sent) to %s: %s", to, body)
        return SmsResult(
            success=True,
            status="sent",
            reference=f"console-{uuid.uuid4().hex[:16]}",
        )


def get_sms_adapter():
    """Return the adapter named by ``MESSAGING_SMS_ADAPTER``.

    The setting holds a dotted path to an SmsAdapter subclass;
    it defaults to the console adapter.
    """
    path = getattr(settings, "MESSAGING_SMS_ADAPTER", DEFAULT_SMS_ADAPTER)
    return import_string(path)()
