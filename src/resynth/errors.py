"""Error types shared across RESYNTH modules."""


class ResynthError(Exception):
    """A user-facing error. The CLI reports the message and exits nonzero."""
