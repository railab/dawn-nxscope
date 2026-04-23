"""CLI helper to set Dawn IO over nxslib IPC control socket."""

import argparse
import struct

from dawn_nxscope.plugin import DawnNxscopePlugin
from nxscli.control_server import ControlClient

# qemu_nxscope_udp.yaml: channel "a" (dummy_notify uint32)
OBJ_PLOT_DUMMY_NOTIFY = 0x41070000


def _parse_int(value: str) -> int:
    return int(value, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default="unix-abstract://nxscope-control",
        help="nxscli control endpoint (unix://, unix-abstract:// or tcp://)",
    )
    parser.add_argument(
        "--sock",
        dest="endpoint",
        help="deprecated alias for --endpoint",
    )
    parser.add_argument(
        "--objid",
        type=_parse_int,
        default=OBJ_PLOT_DUMMY_NOTIFY,
        help="Dawn object id (default: plotted dummy notify)",
    )
    parser.add_argument(
        "--value",
        type=_parse_int,
        required=True,
        help="uint32 value to set",
    )
    args = parser.parse_args()

    client = ControlClient(args.endpoint, timeout=1.0)
    plugin = DawnNxscopePlugin(control=client)
    ack = plugin.set_io(args.objid, struct.pack("<I", args.value))

    if not ack.state:
        err = client.last_error
        if err:
            print(f"ERROR retcode={ack.retcode} detail={err}")
        else:
            print(f"ERROR retcode={ack.retcode}")
        return 1

    print(f"OK state={ack.state} retcode={ack.retcode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
