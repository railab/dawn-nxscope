import struct

import pytest
from nxslib.comm import AckMode
from nxslib.proto.iframe import DParseFrame
from nxslib.proto.iparse import ParseAck

from dawn_nxscope.plugin import (
    DawnExtIds,
    DawnNxscopeError,
    DawnNxscopePlugin,
)

_ACK_OK = ParseAck(state=True, retcode=123)


class _FakeControl:
    def __init__(self, reply=None, ack=_ACK_OK):
        self.last_fid = None
        self.last_payload = None
        self.last_ack_mode = None
        self.last_ack_timeout = None
        self.listeners = {}
        self.reply = reply
        self.ack = ack

    def add_user_frame_listener(self, callback, frame_ids=None):
        lid = len(self.listeners) + 1
        self.listeners[lid] = (callback, frame_ids)
        return lid

    def remove_user_frame_listener(self, listener_id):
        return self.listeners.pop(listener_id, None) is not None

    def deliver(self, fid, data):
        return [
            cb(DParseFrame(fid=fid, data=data))
            for cb, _ in self.listeners.values()
        ]

    def send_user_frame(
        self,
        fid,
        payload,
        ack_mode=AckMode.DISABLED,
        ack_timeout=1.0,
    ):
        self.last_fid = int(fid)
        self.last_payload = payload
        self.last_ack_mode = ack_mode
        self.last_ack_timeout = ack_timeout
        # A GET response frame reaches the listeners before the ACK
        if self.reply is not None and fid in (10, 11):
            objid = struct.unpack_from("<I", payload, 0)[0]
            self.deliver(
                10, struct.pack("<IH", objid, len(self.reply)) + self.reply
            )
        return self.ack


def test_set_io_payload_and_id():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)

    ack = plugin.set_io(0x11223344, b"\xaa\xbb", ack_timeout=0.25)

    assert ack.retcode == 123
    assert control.last_fid == 8
    assert control.last_payload == (
        struct.pack("<IH", 0x11223344, 2) + b"\xaa\xbb"
    )
    assert control.last_ack_mode is AckMode.DISABLED
    assert control.last_ack_timeout == 0.25


def test_set_io_seek_payload_and_id():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)

    plugin.set_io_seek(0x55667788, 0x10, b"\x01\x02\x03")

    assert control.last_fid == 9
    assert control.last_payload == (
        struct.pack("<IIH", 0x55667788, 0x10, 3) + b"\x01\x02\x03"
    )


def test_get_io_payload_and_response():
    control = _FakeControl(reply=b"\x01\x02\x03\x04")
    plugin = DawnNxscopePlugin(control=control)

    data = plugin.get_io(0x11223344, ack_mode=AckMode.ENABLED)

    assert data == b"\x01\x02\x03\x04"
    assert control.last_fid == 10
    assert control.last_payload == struct.pack("<I", 0x11223344)
    assert control.last_ack_mode is AckMode.ENABLED
    assert list(control.listeners.values())[0][1] == [10]


def test_get_io_seek_payload_and_response():
    control = _FakeControl(reply=b"BC00")
    plugin = DawnNxscopePlugin(control=control)

    data = plugin.get_io_seek(0x55667788, 1, 4)

    assert data == b"BC00"
    assert control.last_fid == 11
    assert control.last_payload == struct.pack("<IIH", 0x55667788, 1, 4)


def test_get_io_timeout_and_nack():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)

    with pytest.raises(TimeoutError):
        plugin.get_io(1, timeout=0.01)

    control.ack = ParseAck(state=False, retcode=-1)
    with pytest.raises(DawnNxscopeError) as exc:
        plugin.get_io(1, ack_mode=AckMode.ENABLED)
    assert exc.value.retcode == -1


def test_on_user_frame_filters():
    plugin = DawnNxscopePlugin()

    assert plugin.on_user_frame(DParseFrame(fid=8, data=bytes(8))) is False
    assert plugin.on_user_frame(DParseFrame(fid=10, data=b"\x00")) is False
    assert plugin.on_user_frame(
        DParseFrame(fid=10, data=struct.pack("<IH", 7, 1) + b"\xaa")
    )


def test_optional_ack_returns_success_when_unsupported():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)

    ack = plugin.set_io(1, b"\x00")

    assert ack.state is True
    assert ack.retcode == 123


def test_input_range_validation():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)

    with pytest.raises(ValueError):
        plugin.set_io(-1, b"\x00")

    with pytest.raises(ValueError):
        plugin.set_io(0x1_0000_0000, b"\x00")

    with pytest.raises(ValueError):
        plugin.set_io_seek(1, -1, b"\x00")

    with pytest.raises(ValueError):
        plugin.set_io_seek(1, 0x1_0000_0000, b"\x00")

    with pytest.raises(ValueError):
        plugin.set_io(1, bytes(0x1_0000))

    with pytest.raises(ValueError):
        plugin.set_io_seek(1, 0, bytes(0x1_0000))

    with pytest.raises(ValueError):
        plugin.get_io(0x1_0000_0000)

    with pytest.raises(ValueError):
        plugin.get_io_seek(1, -1, 4)

    with pytest.raises(ValueError):
        plugin.get_io_seek(1, 0, 0x1_0000)


def test_plugin_register_lifecycle():
    control = _FakeControl()
    plugin = DawnNxscopePlugin()

    with pytest.raises(RuntimeError):
        plugin.set_io(1, b"\x00")

    plugin.on_register(control)
    plugin.set_io(1, b"\x00")
    assert control.last_fid == 8
    assert control.listeners == {}

    plugin.on_unregister()
    with pytest.raises(RuntimeError):
        plugin.set_io(1, b"\x00")


def test_standalone_listener_lifecycle():
    control = _FakeControl()
    plugin = DawnNxscopePlugin(control=control)
    assert len(control.listeners) == 1

    plugin.on_unregister()
    assert control.listeners == {}
    with pytest.raises(RuntimeError):
        plugin.get_io(1)


def test_custom_extension_ids():
    control = _FakeControl()
    ext_ids = DawnExtIds(set_io=18, set_io_seek=19, get_io=20, get_io_seek=21)
    plugin = DawnNxscopePlugin(control=control, ext_ids=ext_ids)

    assert plugin.extension_ids == ext_ids

    plugin.set_io(1, b"\x00")
    assert control.last_fid == 18

    plugin.set_io_seek(1, 0, b"\x00")
    assert control.last_fid == 19

    control.reply = b"\x00"
    with pytest.raises(TimeoutError):
        # fake replies on ids 10/11 only, so the custom ids time out
        plugin.get_io(1, timeout=0.01)
    assert control.last_fid == 20
    with pytest.raises(TimeoutError):
        plugin.get_io_seek(1, 0, 1, timeout=0.01)
    assert control.last_fid == 21
