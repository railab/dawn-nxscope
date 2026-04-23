# dawn-nxscope

`dawn-nxscope` provides a Dawn-specific NxScope extension plugin for
`nxslib`.

Main Dawn project: [railab/dawn](https://github.com/railab/dawn).

This package is experimental. It extends NxScope for Dawn so host tools can
control Dawn IO objects over the NxScope protocol.

It implements Dawn user-extension commands over NxScope:
- `SET_IO` (user id `8`)
- `SET_IO_SEEK` (user id `9`)

The plugin uses the public nxslib control surface
(`send_user_frame`) and is transport-agnostic (serial, UDP, RTT,
dummy, or custom interfaces).

## Usage

### Standalone helper

```python
from dawn_nxscope.plugin import DawnNxscopePlugin
from nxslib.intf.serial import Serial
from nxslib.nxscope import NxscopeHandler
from nxslib.proto.parse import Parser

intf = Serial("/dev/ttyUSB0")
parse = Parser()

with NxscopeHandler(intf, parse) as nxscope:
    dawn = DawnNxscopePlugin(control=nxscope)
    dawn.set_io(0x50200001, b"\x01\x00\x00\x00")
    dawn.set_io_seek(0x50A00001, 16, b"\x11\x22\x33")
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
