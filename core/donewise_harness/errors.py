"""Exceptions shared by the harness and adapters."""


class ReadUnavailable(RuntimeError):
    """The provider could not be read (timeout, 5xx). The harness turns this into UNKNOWN."""
