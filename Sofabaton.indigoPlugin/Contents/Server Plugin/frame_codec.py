"""Binary frame codec for Sofabaton X1/X1S protocol.

Wire format: [0xA5] [0x5A] [opcode_hi] [opcode_lo] [payload...] [checksum]
Checksum = sum(all preceding bytes) & 0xFF
"""
import struct

from protocol_const import SYNC0, SYNC1, MIN_FRAME_SIZE, OP_CALL_ME


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
    Scans for sync bytes and validates checksums to find frame boundaries.
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

        found = False
        for end in range(pos + MIN_FRAME_SIZE, len(buffer) + 1):
            candidate = buffer[pos:end]
            expected = sum(candidate[:-1]) & 0xFF
            if candidate[-1] == expected:
                frames.append(candidate)
                pos = end
                found = True
                break

        if not found:
            break

    remaining = buffer[pos:] if pos < len(buffer) else b""
    return frames, remaining


def _find_sync(buffer, start):
    """Find the next sync byte pair starting from offset."""
    for i in range(start, len(buffer) - 1):
        if buffer[i] == SYNC0 and buffer[i + 1] == SYNC1:
            return i
    return -1
