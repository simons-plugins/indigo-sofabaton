"""Tests for X1/X1S opcode response handlers."""
import struct
import sys
from pathlib import Path

SERVER_PLUGIN_DIR = (
    Path(__file__).parent.parent
    / "Sofabaton.indigoPlugin"
    / "Contents"
    / "Server Plugin"
)
sys.path.insert(0, str(SERVER_PLUGIN_DIR))

from protocol_const import (
    OP_CATALOG_ROW_DEVICE, OP_CATALOG_ROW_ACTIVITY,
    OP_X1_DEVICE, OP_X1_ACTIVITY,
    OP_DEVBTN_SINGLE, OP_DEVBTN_TAIL, OP_ACK_READY,
)
from frame_codec import build_frame


def _build_catalog_device_frame(device_id, name):
    """Build a mock catalog device row frame.
    Layout: device_id at bytes 2-4 (3 bytes big-endian within payload),
    name as UTF-16BE at payload bytes 32-92.
    """
    payload = bytearray(96)
    payload[2] = (device_id >> 16) & 0xFF
    payload[3] = (device_id >> 8) & 0xFF
    payload[4] = device_id & 0xFF
    encoded = name.encode("utf-16-be")[:60]
    payload[32:32 + len(encoded)] = encoded
    return bytes(payload)


def _build_catalog_activity_frame(activity_id, name, active=False):
    """Build a mock catalog activity row frame.
    Layout: activity_id at bytes 2-4, active flag at byte 31,
    name as UTF-16BE at payload bytes 32-92.
    """
    payload = bytearray(96)
    payload[2] = (activity_id >> 16) & 0xFF
    payload[3] = (activity_id >> 8) & 0xFF
    payload[4] = activity_id & 0xFF
    payload[31] = 1 if active else 0
    encoded = name.encode("utf-16-be")[:60]
    payload[32:32 + len(encoded)] = encoded
    return bytes(payload)


def _build_x1_activity_frame(activity_id, name, active=False):
    """Build a mock X1 activity row frame.
    X1 layout: active flag at byte 5, name UTF-8 at 28-58.
    """
    payload = bytearray(64)
    payload[2] = (activity_id >> 16) & 0xFF
    payload[3] = (activity_id >> 8) & 0xFF
    payload[4] = activity_id & 0xFF
    payload[5] = 1 if active else 0
    encoded = name.encode("utf-8")[:30]
    payload[28:28 + len(encoded)] = encoded
    return bytes(payload)


def _build_x1_device_frame(device_id, name):
    """Build a mock X1 device row frame.
    X1 uses UTF-8 at payload offset 28-58.
    """
    payload = bytearray(64)
    payload[2] = (device_id >> 16) & 0xFF
    payload[3] = (device_id >> 8) & 0xFF
    payload[4] = device_id & 0xFF
    encoded = name.encode("utf-8")[:30]
    payload[28:28 + len(encoded)] = encoded
    return bytes(payload)


class TestParseDeviceCatalogRow:
    def test_extracts_device_id(self):
        from opcode_handlers import parse_device_catalog_row
        payload = _build_catalog_device_frame(5, "Samsung TV")
        result = parse_device_catalog_row(payload, is_x1=False)
        assert result["device_id"] == 5

    def test_extracts_device_name_utf16(self):
        from opcode_handlers import parse_device_catalog_row
        payload = _build_catalog_device_frame(5, "Samsung TV")
        result = parse_device_catalog_row(payload, is_x1=False)
        assert result["name"] == "Samsung TV"

    def test_extracts_x1_device_name_utf8(self):
        from opcode_handlers import parse_device_catalog_row
        payload = _build_x1_device_frame(3, "Denon AVR")
        result = parse_device_catalog_row(payload, is_x1=True)
        assert result["device_id"] == 3
        assert result["name"] == "Denon AVR"


class TestParseActivityCatalogRow:
    def test_extracts_activity_id(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_catalog_activity_frame(101, "Watch TV")
        result = parse_activity_catalog_row(payload, is_x1=False)
        assert result["activity_id"] == 101

    def test_extracts_activity_name(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_catalog_activity_frame(101, "Watch TV")
        result = parse_activity_catalog_row(payload, is_x1=False)
        assert result["name"] == "Watch TV"

    def test_extracts_active_state_false(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_catalog_activity_frame(101, "Watch TV", active=False)
        result = parse_activity_catalog_row(payload, is_x1=False)
        assert result["active"] is False

    def test_extracts_active_state_true(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_catalog_activity_frame(102, "Music", active=True)
        result = parse_activity_catalog_row(payload, is_x1=False)
        assert result["active"] is True

    def test_x1_extracts_active_from_byte_5(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_x1_activity_frame(101, "Watch TV", active=True)
        result = parse_activity_catalog_row(payload, is_x1=True)
        assert result["active"] is True
        assert result["name"] == "Watch TV"

    def test_x1_inactive_from_byte_5(self):
        from opcode_handlers import parse_activity_catalog_row
        payload = _build_x1_activity_frame(101, "Watch TV", active=False)
        result = parse_activity_catalog_row(payload, is_x1=True)
        assert result["active"] is False


class TestParseButtonRecord:
    def test_extracts_button_label(self):
        from opcode_handlers import parse_button_record
        label = "Power"
        label_bytes = label.encode("ascii")
        record = bytes([5, 1]) + bytes(7) + label_bytes
        result = parse_button_record(record)
        assert result["device_id"] == 5
        assert result["command_id"] == 1
        assert result["label"] == "Power"


class TestDispatchOpcode:
    def test_ack_ready_returns_type(self):
        from opcode_handlers import dispatch_opcode
        result = dispatch_opcode(OP_ACK_READY, b"", is_x1=False)
        assert result["type"] == "ack_ready"

    def test_unknown_opcode_returns_none(self):
        from opcode_handlers import dispatch_opcode
        result = dispatch_opcode(0xFFFF, b"", is_x1=False)
        assert result is None

    def test_device_row_dispatches(self):
        from opcode_handlers import dispatch_opcode
        payload = _build_catalog_device_frame(5, "TV")
        result = dispatch_opcode(OP_CATALOG_ROW_DEVICE, payload, is_x1=False)
        assert result["type"] == "device"
        assert result["data"]["device_id"] == 5

    def test_activity_row_dispatches(self):
        from opcode_handlers import dispatch_opcode
        payload = _build_catalog_activity_frame(101, "Watch TV")
        result = dispatch_opcode(OP_CATALOG_ROW_ACTIVITY, payload, is_x1=False)
        assert result["type"] == "activity"
        assert result["data"]["activity_id"] == 101

    def test_button_tail_returns_type(self):
        from opcode_handlers import dispatch_opcode
        result = dispatch_opcode(OP_DEVBTN_TAIL, b"", is_x1=False)
        assert result["type"] == "buttons_complete"
