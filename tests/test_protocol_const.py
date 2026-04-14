"""Tests for X1/X1S protocol constants."""
import sys
from pathlib import Path

SERVER_PLUGIN_DIR = (
    Path(__file__).parent.parent
    / "Sofabaton.indigoPlugin"
    / "Contents"
    / "Server Plugin"
)
sys.path.insert(0, str(SERVER_PLUGIN_DIR))


class TestSyncBytes:
    def test_sync_bytes_values(self):
        from protocol_const import SYNC0, SYNC1
        assert SYNC0 == 0xA5
        assert SYNC1 == 0x5A

    def test_min_frame_size(self):
        from protocol_const import MIN_FRAME_SIZE
        assert MIN_FRAME_SIZE == 5


class TestOpcodes:
    def test_request_opcodes_exist(self):
        from protocol_const import (
            OP_CALL_ME, OP_REQ_DEVICES, OP_REQ_ACTIVITIES,
            OP_REQ_BUTTONS, OP_REQ_COMMANDS, OP_REQ_ACTIVATE,
            OP_REQ_ACTIVITY_MAP,
        )
        assert OP_REQ_DEVICES == 0x000A
        assert OP_REQ_ACTIVITIES == 0x003A
        assert OP_REQ_BUTTONS == 0x023C
        assert OP_REQ_COMMANDS == 0x025C
        assert OP_REQ_ACTIVATE == 0x023F
        assert OP_REQ_ACTIVITY_MAP == 0x016C

    def test_response_opcodes_exist(self):
        from protocol_const import (
            OP_ACK_READY, OP_CATALOG_ROW_DEVICE, OP_CATALOG_ROW_ACTIVITY,
            OP_X1_DEVICE, OP_X1_ACTIVITY,
        )
        assert OP_ACK_READY == 0x0160
        assert OP_CATALOG_ROW_DEVICE == 0xD50B
        assert OP_CATALOG_ROW_ACTIVITY == 0xD53B
        assert OP_X1_DEVICE == 0x7B0B
        assert OP_X1_ACTIVITY == 0x7B3B

    def test_button_opcodes_exist(self):
        from protocol_const import (
            OP_DEVBTN_HEADER, OP_DEVBTN_PAGE,
            OP_DEVBTN_SINGLE, OP_DEVBTN_TAIL,
        )
        assert OP_DEVBTN_HEADER == 0xD95D
        assert OP_DEVBTN_PAGE == 0xD55D
        assert OP_DEVBTN_SINGLE == 0x4D5D
        assert OP_DEVBTN_TAIL == 0x495D


class TestOpcodeFamilies:
    def test_family_constants(self):
        from protocol_const import (
            FAMILY_DEV_ROW, FAMILY_ACT_ROW,
            FAMILY_MACROS, FAMILY_KEYMAP, FAMILY_DEVBTNS,
        )
        assert FAMILY_DEV_ROW == 0x0B
        assert FAMILY_ACT_ROW == 0x3B
        assert FAMILY_MACROS == 0x13
        assert FAMILY_KEYMAP == 0x3D
        assert FAMILY_DEVBTNS == 0x5D


class TestPorts:
    def test_default_ports(self):
        from protocol_const import (
            UDP_CALLME_PORT, TCP_BASE_PORT, TCP_PORT_RANGE,
            CALLME_INTERVAL, CALLME_JITTER, COMMAND_DELAY,
        )
        assert UDP_CALLME_PORT == 8102
        assert TCP_BASE_PORT == 8200
        assert TCP_PORT_RANGE == 32
        assert CALLME_INTERVAL == 2.0
        assert CALLME_JITTER == 0.25
        assert COMMAND_DELAY == 0.2


class TestHubVersions:
    def test_hub_version_map(self):
        from protocol_const import HUB_VERSIONS
        assert HUB_VERSIONS["1"] == "X1"
        assert HUB_VERSIONS["2"] == "X1S"
        assert HUB_VERSIONS["3"] == "X2"

    def test_mdns_service_types(self):
        from protocol_const import MDNS_X1, MDNS_X2
        assert MDNS_X1 == "_x1hub._udp.local."
        assert MDNS_X2 == "_sofabaton_hub._udp.local."
