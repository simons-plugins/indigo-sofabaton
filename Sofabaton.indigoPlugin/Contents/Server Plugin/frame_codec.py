"""Binary frame codec for Sofabaton X1/X1S protocol.

Wire format: [0xA5] [0x5A] [opcode_hi] [opcode_lo] [payload...] [checksum]
Checksum = sum(all preceding bytes) & 0xFF
"""
import struct

from protocol_const import (
    SYNC0, SYNC1, MIN_FRAME_SIZE, OP_CALL_ME,
    OP_ACK_READY,
    OP_CATALOG_ROW_DEVICE, OP_CATALOG_ROW_ACTIVITY,
    OP_X1_DEVICE, OP_X1_ACTIVITY,
    OP_DEVBTN_HEADER, OP_DEVBTN_PAGE, OP_DEVBTN_SINGLE, OP_DEVBTN_TAIL,
)

# Known frame sizes (sync + opcode + payload + checksum) for opcodes
# where the hub sends fixed-length responses. Used by extract_frames
# to avoid greedy checksum scanning on large payloads.
_KNOWN_FRAME_SIZES = {
    OP_ACK_READY: 5,             # no payload
    OP_DEVBTN_TAIL: 5,           # no payload
    OP_CATALOG_ROW_DEVICE: 101,  # 96-byte payload
    OP_CATALOG_ROW_ACTIVITY: 101,# 96-byte payload
    OP_X1_DEVICE: 69,            # 64-byte payload
    OP_X1_ACTIVITY: 69,          # 64-byte payload
}


def build_frame(opcode, payload=b""):
    """Build a binary frame with sync, opcode, payload, and checksum."""
    header = bytes([SYNC0, SYNC1, (opcode >> 8) & 0xFF, opcode & 0xFF])
    body = header + payload
    checksum = sum(body) & 0xFF
    return body + bytes([checksum])


def build_callme_packet(local_ip, local_port):
    """Build a CALL_ME UDP packet telling the hub where to connect back.

    Format: [sync(2)] [opcode(2)] [zeros(6)] [ip(4)] [port(2, big-endian)] [checksum(1)]
    """
    ip_bytes = bytes(int(b) for b in local_ip.split("."))
    port_bytes = struct.pack(">H", local_port)
    opcode_bytes = bytes([(OP_CALL_ME >> 8) & 0xFF, OP_CALL_ME & 0xFF])
    body = bytes([SYNC0, SYNC1]) + opcode_bytes + bytes(6) + ip_bytes + port_bytes
    checksum = sum(body) & 0xFF
    return body + bytes([checksum])


def parse_frame(data):
    """Parse a complete binary frame. Returns (opcode, payload).

    Raises ValueError if frame is invalid.
    """
    if len(data) < MIN_FRAME_SIZE:
        raise ValueError("Frame too short: %d bytes" % len(data))
    if data[0] != SYNC0 or data[1] != SYNC1:
        raise ValueError("Invalid sync bytes: 0x%02X 0x%02X" % (data[0], data[1]))

    expected_checksum = sum(data[:-1]) & 0xFF
    if data[-1] != expected_checksum:
        raise ValueError(
            "Bad checksum: expected 0x%02X, got 0x%02X" % (expected_checksum, data[-1])
        )

    opcode = (data[2] << 8) | data[3]
    payload = data[4:-1]
    return opcode, bytes(payload)


def extract_frames(buffer):
    """Extract complete frames from a byte buffer.

    Returns (list_of_raw_frames, remaining_bytes).

    Only frames whose opcode appears in _KNOWN_FRAME_SIZES are extracted.
    Unknown opcodes advance the scan past the sync bytes without inventing
    a frame boundary — a coincidental checksum byte inside a legitimate
    longer payload must not be able to produce a false short frame.
    """
    frames = []
    pos = 0

    while pos < len(buffer):
        sync_pos = _find_sync(buffer, pos)
        if sync_pos < 0:
            break
        pos = sync_pos

        if pos + MIN_FRAME_SIZE > len(buffer):
            break

        opcode = (buffer[pos + 2] << 8) | buffer[pos + 3]
        known_size = _KNOWN_FRAME_SIZES.get(opcode)

        if known_size is None:
            # Unknown opcode: advance past the sync and keep scanning.
            # We deliberately do NOT greedily search for a matching checksum:
            # that is O(N^2) and can mis-frame on coincidental checksum bytes.
            pos += 2
            continue

        end = pos + known_size
        if end > len(buffer):
            break  # incomplete frame — wait for more data

        candidate = buffer[pos:end]
        expected = sum(candidate[:-1]) & 0xFF
        if candidate[-1] == expected:
            frames.append(candidate)
            pos = end
        else:
            # Checksum mismatch — skip this sync and try next
            pos += 2

    remaining = buffer[pos:] if pos < len(buffer) else b""
    return frames, remaining


def _find_sync(buffer, start):
    """Find the next sync byte pair starting from offset.

    Safe against a lone SYNC0 at the final byte (where SYNC1 would be out
    of range) — the caller will get back -1 and wait for more data.
    """
    end = len(buffer) - 1
    for i in range(start, end):
        if buffer[i] == SYNC0 and buffer[i + 1] == SYNC1:
            return i
    return -1
