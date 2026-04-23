"""Dawn NxScope extension plugin for nxslib."""

import struct
import threading
from dataclasses import dataclass

from nxslib.comm import AckMode
from nxslib.plugin import INxscopeControl, INxscopePlugin
from nxslib.proto.iparse import ParseAck


@dataclass(frozen=True)
class DawnExtIds:
    """Dawn NxScope user extension command IDs."""

    set_io: int = 8
    set_io_seek: int = 9


class DawnNxscopePlugin(INxscopePlugin):
    """Dawn extension plugin for nxslib.

    The plugin can be used in two ways:
    - standalone helper with a provided nxslib control/handler object
    - as a registered nxslib plugin via on_register(control)

    Control object must expose send_user_frame(fid, payload, ...).
    """

    name = "dawn_nxscope"

    def __init__(
        self,
        control: INxscopeControl | None = None,
        ext_ids: DawnExtIds | None = None,
    ) -> None:
        """Initialize plugin.

        :param control: nxslib control surface or NxscopeHandler
        :param ext_ids: optional user-extension IDs
        """
        self._control = control
        self._ext_ids = ext_ids or DawnExtIds()
        self._tx_lock = threading.Lock()

    def on_register(self, control: INxscopeControl) -> None:
        """Capture nxslib control surface on plugin registration."""
        self._control = control

    def on_unregister(self) -> None:
        """Drop control surface on plugin unregistration."""
        self._control = None

    def _validate_u32(self, value: int, name: str) -> None:
        if value < 0 or value > 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in uint32")

    def _write_user(
        self, fid: int, payload: bytes, timeout: float
    ) -> ParseAck:
        if self._control is None:
            raise RuntimeError("plugin is not attached to nxslib control")

        # Dawn's current user-extension handlers do not require ACK support.
        with self._tx_lock:
            return self._control.send_user_frame(
                fid,
                payload,
                ack_mode=AckMode.DISABLED,
                ack_timeout=timeout,
            )

    def set_io(
        self,
        objid: int,
        data: bytes | bytearray | memoryview,
        ack_timeout: float = 1.0,
    ) -> ParseAck:
        """Send Dawn set-IO request (user id 8 by default).

        Payload format:
        - uint32 objid (little-endian)
        - uint16 size  (little-endian)
        - raw data bytes
        """
        raw = bytes(data)
        self._validate_u32(objid, "objid")

        if len(raw) > 0xFFFF:
            raise ValueError("data too large for uint16 size field")

        payload = struct.pack("<IH", objid, len(raw)) + raw
        return self._write_user(self._ext_ids.set_io, payload, ack_timeout)

    def set_io_seek(
        self,
        objid: int,
        offset: int,
        data: bytes | bytearray | memoryview,
        ack_timeout: float = 1.0,
    ) -> ParseAck:
        """Send Dawn seekable set-IO request (user id 9 by default).

        Payload format:
        - uint32 objid  (little-endian)
        - uint32 offset (little-endian)
        - uint16 size   (little-endian)
        - raw data bytes
        """
        raw = bytes(data)
        self._validate_u32(objid, "objid")
        self._validate_u32(offset, "offset")

        if len(raw) > 0xFFFF:
            raise ValueError("data too large for uint16 size field")

        payload = struct.pack("<IIH", objid, offset, len(raw)) + raw
        return self._write_user(
            self._ext_ids.set_io_seek, payload, ack_timeout
        )

    @property
    def extension_ids(self) -> DawnExtIds:
        """Get active extension IDs."""
        return self._ext_ids
