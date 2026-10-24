class HookRelayError(Exception):
    """Base exception for expected HookRelay failures."""


class NotFoundError(HookRelayError):
    """Raised when a requested endpoint or event does not exist."""


class UnsafeTargetError(HookRelayError):
    """Raised when a target URL could reach a local or private network address."""
