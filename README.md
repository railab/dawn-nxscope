# dawn-nxscope

`dawn-nxscope` provides a Dawn-specific NxScope extension plugin for
`nxslib`.

Main Dawn project: [railab/dawn](https://github.com/railab/dawn).

This package is experimental. It extends NxScope for Dawn so host tools can
control Dawn IO objects over the NxScope protocol.

It implements Dawn user-extension commands over NxScope:
- `SET_IO` (user id `8`): `[objid:4][size:2][data]`
- `SET_IO_SEEK` (user id `9`): `[objid:4][offset:4][size:2][data]`
- `GET_IO` (user id `10`): `[objid:4]`
- `GET_IO_SEEK` (user id `11`): `[objid:4][offset:4][size:2]`

Both GET requests are answered with a user frame id `10` carrying
`[objid:4][size:2][data]`, sent before the ACK. `get_io()` /
`get_io_seek()` return the data bytes, raise `TimeoutError` when no
response arrives and `DawnNxscopeError` on a negative ACK.

The plugin uses the public nxslib control surface
(`send_user_frame`, `add_user_frame_listener`) and is transport-agnostic
(serial, UDP, RTT, dummy, or custom interfaces).

## Usage

### Standalone helper

```python
from dawn_nxscope.plugin import DawnNxscopePlugin
from nxslib.comm import AckMode
from nxslib.intf.serial import Serial
from nxslib.nxscope import NxscopeHandler
from nxslib.proto.parse import Parser

intf = Serial("/dev/ttyUSB0")
parse = Parser()

with NxscopeHandler(intf, parse) as nxscope:
    dawn = DawnNxscopePlugin(control=nxscope)
    dawn.set_io(0x50200001, b"\x01\x00\x00\x00")
    dawn.set_io_seek(0x50A00001, 16, b"\x11\x22\x33")
    value = dawn.get_io(0x50200001, ack_mode=AckMode.ENABLED)
    chunk = dawn.get_io_seek(0x50A00001, 16, 32)
```

### As nxslib plugin

```python
from dawn_nxscope.plugin import DawnNxscopePlugin

dawn = DawnNxscopePlugin()
nxscope.register_plugin(dawn)

# control object is injected via on_register()
dawn.set_io(0x50200001, b"\x01\x00\x00\x00")

nxscope.unregister_plugin("dawn_nxscope")
```

### Plotter + external setter (separate processes)

In process A (plotter / transport owner):

```bash
nxscli --control-server \
  --control-endpoint unix-abstract://nxscope-control \
  ...existing nxscli args...
```

In process B (setter):

```bash
python test.py --endpoint unix-abstract://nxscope-control --value 123
```

This keeps one transport owner while allowing external set requests.
