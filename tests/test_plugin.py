import struct

import pytest
from nxslib.comm import AckMode
from nxslib.proto.iparse import ParseAck

from dawn_nxscope.plugin import DawnExtIds, DawnNxscopePlugin


class _FakeControl:
    def __init__(self):
        self.last_fid = None
        self.last_payload = None
        self.last_ack_mode = None
        self.last_ack_timeout = None

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
        return ParseAck(state=True, retcode=123)


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


def test_plugin_register_lifecycle():
    control = _FakeControl()
    plugin = DawnNxscopePlugin()

    with pytest.raises(RuntimeError):
        plugin.set_io(1, b"\x00")

    plugin.on_register(control)
    plugin.set_io(1, b"\x00")
    assert control.last_fid == 8

    plugin.on_unregister()
    with pytest.raises(RuntimeError):
        plugin.set_io(1, b"\x00")


def test_custom_extension_ids():
    control = _FakeControl()
    ext_ids = DawnExtIds(set_io=18, set_io_seek=19)
    plugin = DawnNxscopePlugin(control=control, ext_ids=ext_ids)

    assert plugin.extension_ids == ext_ids

    plugin.set_io(1, b"\x00")
    assert control.last_fid == 18

    plugin.set_io_seek(1, 0, b"\x00")
    assert control.last_fid == 19
