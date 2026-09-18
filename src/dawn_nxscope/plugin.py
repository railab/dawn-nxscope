"""Dawn NxScope extension plugin for nxslib."""

import struct
import threading
from dataclasses import dataclass
from typing import Any

from nxslib.comm import AckMode
from nxslib.plugin import INxscopeControl, INxscopePlugin
from nxslib.proto.iframe import DParseFrame
from nxslib.proto.iparse import ParseAck

# GET_IO response header: uint32 objid + uint16 size (little-endian)
_RESP_HDR = struct.Struct("<IH")


@dataclass(frozen=True)
class DawnExtIds:
    """Dawn NxScope user extension command IDs."""

    set_io: int = 8
    set_io_seek: int = 9
    get_io: int = 10
    get_io_seek: int = 11


class DawnNxscopeError(RuntimeError):
    """Dawn user request rejected by the device (negative ACK retcode)."""

    def __init__(self, retcode: int) -> None:
        """Initialize with the ACK return code."""
        super().__init__(f"dawn request rejected: retcode={retcode}")
        self.retcode = retcode


class DawnNxscopePlugin(INxscopePlugin):
    """Dawn extension plugin for nxslib.

    The plugin can be used in two ways:
    - standalone helper with a provided nxslib control/handler object
    - as a registered nxslib plugin via on_register(control)

    Control object must expose send_user_frame(fid, payload, ...).
    GET requests need the control to deliver user frames: standalone the
    plugin registers its own listener (add_user_frame_listener), as a
    registered plugin nxslib routes them to on_user_frame().
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
        self._resp_cond = threading.Condition()
        self._resp: dict[int, bytes] = {}
        self._listener_id: int | None = None
        if control is not None:
            self._listen(control)

    def _listen(self, control: Any) -> None:
        add = getattr(control, "add_user_frame_listener", None)
        if callable(add):
            self._listener_id = add(self.on_user_frame, [self._ext_ids.get_io])

    def on_register(self, control: INxscopeControl) -> None:
        """Capture nxslib control surface on plugin registration."""
        self._control = control

    def on_unregister(self) -> None:
        """Drop control surface on plugin unregistration."""
        if self._listener_id is not None:
            remove = getattr(self._control, "remove_user_frame_listener", None)
            if callable(remove):
                remove(self._listener_id)
            self._listener_id = None
        self._control = None

    def on_user_frame(self, frame: DParseFrame) -> bool:
        """Capture a GET_IO response frame: [objid:4][size:2][data]."""
        data = bytes(frame.data)
        if int(frame.fid) != self._ext_ids.get_io or len(data) < 6:
            return False

        objid, size = _RESP_HDR.unpack_from(data, 0)
        with self._resp_cond:
            self._resp[objid] = data[6 : 6 + size]
            self._resp_cond.notify_all()
        return True

    def _validate_u32(self, value: int, name: str) -> None:
        if value < 0 or value > 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in uint32")

    def _validate_u16(self, value: int, name: str) -> None:
        if value < 0 or value > 0xFFFF:
            raise ValueError(f"{name} must fit in uint16")

    def _send(
        self, fid: int, payload: bytes, ack_mode: AckMode, timeout: float
    ) -> ParseAck:
        if self._control is None:
            raise RuntimeError("plugin is not attached to nxslib control")

        return self._control.send_user_frame(
            fid,
            payload,
            ack_mode=ack_mode,
            ack_timeout=timeout,
        )

    def _write_user(
        self, fid: int, payload: bytes, timeout: float, ack_mode: AckMode
    ) -> ParseAck:
        with self._tx_lock:
            return self._send(fid, payload, ack_mode, timeout)

    def _read_user(
        self,
        fid: int,
        payload: bytes,
        objid: int,
        timeout: float,
        ack_mode: AckMode,
        ack_timeout: float,
    ) -> bytes:
        # The data frame precedes the ACK, so with ACK enabled it is
        # already captured when send returns; otherwise wait for it.
        with self._tx_lock:
            with self._resp_cond:
                self._resp.pop(objid, None)

            ack = self._send(fid, payload, ack_mode, ack_timeout)
            if not ack.state:
                raise DawnNxscopeError(ack.retcode)

            with self._resp_cond:
                if not self._resp_cond.wait_for(
                    lambda: objid in self._resp, timeout
                ):
                    raise TimeoutError(
                        f"no GET_IO response for objid 0x{objid:08x}"
                    )
                return self._resp.pop(objid)

    def set_io(
        self,
        objid: int,
        data: bytes | bytearray | memoryview,
        ack_timeout: float = 1.0,
        ack_mode: AckMode = AckMode.DISABLED,
    ) -> ParseAck:
        """Send Dawn set-IO request (user id 8 by default).

        Payload format:
        - uint32 objid (little-endian)
        - uint16 size  (little-endian)
        - raw data bytes
        """
        raw = bytes(data)
        self._validate_u32(objid, "objid")
        self._validate_u16(len(raw), "data size")

        payload = struct.pack("<IH", objid, len(raw)) + raw
        return self._write_user(
            self._ext_ids.set_io, payload, ack_timeout, ack_mode
        )

    def set_io_seek(
        self,
        objid: int,
        offset: int,
        data: bytes | bytearray | memoryview,
        ack_timeout: float = 1.0,
        ack_mode: AckMode = AckMode.DISABLED,
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
        self._validate_u16(len(raw), "data size")

        payload = struct.pack("<IIH", objid, offset, len(raw)) + raw
        return self._write_user(
            self._ext_ids.set_io_seek, payload, ack_timeout, ack_mode
        )

    def get_io(
        self,
        objid: int,
        timeout: float = 1.0,
        ack_timeout: float = 1.0,
        ack_mode: AckMode = AckMode.DISABLED,
    ) -> bytes:
        """Send Dawn get-IO request (user id 10 by default).

        Payload format:
        - uint32 objid (little-endian)

        The device answers with a user frame id 10 carrying
        [objid:4][size:2][data] before the ACK. Returns the data bytes,
        raises TimeoutError when no response arrives within ``timeout``
        and DawnNxscopeError on a negative ACK.
        """
        self._validate_u32(objid, "objid")

        payload = struct.pack("<I", objid)
        return self._read_user(
            self._ext_ids.get_io,
            payload,
            objid,
            timeout,
            ack_mode,
            ack_timeout,
        )

    def get_io_seek(
        self,
        objid: int,
        offset: int,
        size: int,
        timeout: float = 1.0,
        ack_timeout: float = 1.0,
        ack_mode: AckMode = AckMode.DISABLED,
    ) -> bytes:
        """Send Dawn seekable get-IO request (user id 11 by default).

        Payload format:
        - uint32 objid  (little-endian)
        - uint32 offset (little-endian)
        - uint16 size   (little-endian)

        Response and errors as for get_io(). ``size`` is capped by the
        device (CONFIG_DAWN_PROTO_NXSCOPE_RXBUF_LEN).
        """
        self._validate_u32(objid, "objid")
        self._validate_u32(offset, "offset")
        self._validate_u16(size, "size")

        payload = struct.pack("<IIH", objid, offset, size)
        return self._read_user(
            self._ext_ids.get_io_seek,
            payload,
            objid,
            timeout,
            ack_mode,
            ack_timeout,
        )

    @property
    def extension_ids(self) -> DawnExtIds:
        """Get active extension IDs."""
        return self._ext_ids
