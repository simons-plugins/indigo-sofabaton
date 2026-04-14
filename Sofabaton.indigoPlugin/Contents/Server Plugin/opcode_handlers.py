"""Parse X1/X1S hub response frames into structured data.

The hub sends catalog rows (devices, activities) and button definitions
as individual frames. This module parses each frame type into dicts.
"""
from protocol_const import (
    OP_ACK_READY,
    OP_CATALOG_ROW_DEVICE, OP_CATALOG_ROW_ACTIVITY,
    OP_X1_DEVICE, OP_X1_ACTIVITY,
    OP_DEVBTN_HEADER, OP_DEVBTN_PAGE, OP_DEVBTN_SINGLE, OP_DEVBTN_TAIL,
    FAMILY_DEV_ROW, FAMILY_ACT_ROW, FAMILY_DEVBTNS,
)


def parse_device_catalog_row(payload, is_x1=False):
    """Parse a device catalog row from frame payload.
    Returns {"device_id": int, "name": str}
    """
    device_id = (payload[2] << 16) | (payload[3] << 8) | payload[4]

    if is_x1:
        name_bytes = payload[28:58]
        name = name_bytes.decode("utf-8", errors="replace").rstrip("\x00").strip()
    else:
        name_bytes = payload[32:92]
        name = name_bytes.decode("utf-16-be", errors="replace").rstrip("\x00").strip()

    return {"device_id": device_id, "name": name}


def parse_activity_catalog_row(payload, is_x1=False):
    """Parse an activity catalog row from frame payload.
    Returns {"activity_id": int, "name": str, "active": bool}
    """
    activity_id = (payload[2] << 16) | (payload[3] << 8) | payload[4]

    if is_x1:
        # X1 layout: active flag at byte 5, name UTF-8 at 28-58
        active = bool(payload[5]) if len(payload) > 5 else False
        name_bytes = payload[28:58]
        name = name_bytes.decode("utf-8", errors="replace").rstrip("\x00").strip()
    else:
        # X1S/X2 layout: active flag at byte 31, name UTF-16BE at 32-92
        active = bool(payload[31]) if len(payload) > 31 else False
        name_bytes = payload[32:92]
        name = name_bytes.decode("utf-16-be", errors="replace").rstrip("\x00").strip()

    return {"activity_id": activity_id, "name": name, "active": active}


def parse_button_record(record):
    """Parse a single button/command record.
    Record format: device_id(1) + command_id(1) + control(7) + label(variable)
    """
    device_id = record[0]
    command_id = record[1]
    label_bytes = record[9:]
    label = _decode_label(label_bytes)
    return {"device_id": device_id, "command_id": command_id, "label": label}


def dispatch_opcode(opcode, payload, is_x1=False):
    """Dispatch a parsed frame to the appropriate handler.
    Returns a dict with "type" key and optional "data", or None for unknown opcodes.
    """
    if opcode == OP_ACK_READY:
        return {"type": "ack_ready"}

    if opcode in (OP_CATALOG_ROW_DEVICE, OP_X1_DEVICE):
        use_x1 = is_x1 or opcode == OP_X1_DEVICE
        return {"type": "device", "data": parse_device_catalog_row(payload, is_x1=use_x1)}

    if opcode in (OP_CATALOG_ROW_ACTIVITY, OP_X1_ACTIVITY):
        use_x1 = is_x1 or opcode == OP_X1_ACTIVITY
        return {"type": "activity", "data": parse_activity_catalog_row(payload, is_x1=use_x1)}

    if opcode == OP_DEVBTN_TAIL:
        return {"type": "buttons_complete"}

    if opcode in (OP_DEVBTN_HEADER, OP_DEVBTN_PAGE, OP_DEVBTN_SINGLE):
        return {"type": "button_data", "opcode": opcode, "payload": payload}

    family = opcode & 0xFF
    if family == FAMILY_DEV_ROW:
        return {"type": "device", "data": parse_device_catalog_row(payload, is_x1=is_x1)}
    if family == FAMILY_ACT_ROW:
        return {"type": "activity", "data": parse_activity_catalog_row(payload, is_x1=is_x1)}

    return None


def _decode_label(label_bytes):
    """Decode a label using multiple encoding strategies."""
    if not label_bytes:
        return ""

    try:
        text = label_bytes.decode("ascii").rstrip("\x00").strip()
        if text and text.isprintable():
            return text
    except (UnicodeDecodeError, ValueError):
        pass

    try:
        text = label_bytes.decode("utf-8").rstrip("\x00").strip()
        if text:
            return text
    except (UnicodeDecodeError, ValueError):
        pass

    return label_bytes.decode("latin-1").rstrip("\x00").strip()
