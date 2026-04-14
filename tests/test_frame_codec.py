"""Tests for X1/X1S binary frame codec."""
import sys
from pathlib import Path

SERVER_PLUGIN_DIR = (
    Path(__file__).parent.parent
    / "Sofabaton.indigoPlugin"
    / "Contents"
    / "Server Plugin"
)
sys.path.insert(0, str(SERVER_PLUGIN_DIR))

from protocol_const import SYNC0, SYNC1, OP_REQ_DEVICES, OP_REQ_ACTIVITIES, OP_ACK_READY


class TestBuildFrame:
    def test_frame_starts_with_sync_bytes(self):
        from frame_codec import build_frame
        frame = build_frame(OP_REQ_DEVICES)
        assert frame[0] == SYNC0
        assert frame[1] == SYNC1

    def test_frame_opcode_big_endian(self):
        from frame_codec import build_frame
        frame = build_frame(OP_REQ_DEVICES)  # 0x000A
        assert frame[2] == 0x00
        assert frame[3] == 0x0A

    def test_frame_no_payload_length(self):
        from frame_codec import build_frame
        frame = build_frame(OP_REQ_DEVICES)
        assert len(frame) == 5

    def test_frame_with_payload(self):
        from frame_codec import build_frame
        payload = bytes([0x01, 0x02, 0x03])
        frame = build_frame(OP_REQ_DEVICES, payload)
        assert len(frame) == 8
        assert frame[4:7] == payload

    def test_checksum_is_sum_of_preceding_bytes_mod_256(self):
        from frame_codec import build_frame
        frame = build_frame(OP_REQ_DEVICES)
        expected_checksum = sum(frame[:-1]) & 0xFF
        assert frame[-1] == expected_checksum

    def test_checksum_with_payload(self):
        from frame_codec import build_frame
        payload = bytes([0xFF, 0x01])
        frame = build_frame(0x1234, payload)
        expected_checksum = sum(frame[:-1]) & 0xFF
        assert frame[-1] == expected_checksum


class TestBuildCallMePacket:
    def test_callme_packet_structure(self):
        from frame_codec import build_callme_packet
        packet = build_callme_packet("192.168.1.100", 8200)
        assert packet[0] == SYNC0
        assert packet[1] == SYNC1
        assert packet[4:10] == bytes(6)

    def test_callme_ip_bytes(self):
        from frame_codec import build_callme_packet
        packet = build_callme_packet("192.168.1.100", 8200)
        assert packet[10] == 192
        assert packet[11] == 168
        assert packet[12] == 1
        assert packet[13] == 100

    def test_callme_port_big_endian(self):
        from frame_codec import build_callme_packet
        packet = build_callme_packet("192.168.1.100", 8200)
        port = (packet[14] << 8) | packet[15]
        assert port == 8200

    def test_callme_checksum(self):
        from frame_codec import build_callme_packet
        packet = build_callme_packet("10.0.0.1", 8200)
        expected = sum(packet[:-1]) & 0xFF
        assert packet[-1] == expected


class TestParseFrame:
    def test_parse_valid_frame(self):
        from frame_codec import build_frame, parse_frame
        original = build_frame(OP_REQ_DEVICES, bytes([0x01, 0x02]))
        opcode, payload = parse_frame(original)
        assert opcode == OP_REQ_DEVICES
        assert payload == bytes([0x01, 0x02])

    def test_parse_no_payload(self):
        from frame_codec import build_frame, parse_frame
        original = build_frame(OP_REQ_ACTIVITIES)
        opcode, payload = parse_frame(original)
        assert opcode == OP_REQ_ACTIVITIES
        assert payload == b""

    def test_parse_invalid_sync_raises(self):
        from frame_codec import parse_frame
        import pytest
        bad = bytes([0x00, 0x00, 0x00, 0x0A, 0x0A])
        with pytest.raises(ValueError, match="sync"):
            parse_frame(bad)

    def test_parse_bad_checksum_raises(self):
        from frame_codec import build_frame, parse_frame
        import pytest
        frame = bytearray(build_frame(OP_REQ_DEVICES))
        frame[-1] = (frame[-1] + 1) & 0xFF
        with pytest.raises(ValueError, match="checksum"):
            parse_frame(bytes(frame))

    def test_parse_too_short_raises(self):
        from frame_codec import parse_frame
        import pytest
        with pytest.raises(ValueError, match="short"):
            parse_frame(bytes([0xA5, 0x5A, 0x00]))


class TestExtractFrames:
    def test_extract_single_complete_frame(self):
        from frame_codec import build_frame, extract_frames
        frame = build_frame(OP_ACK_READY)
        frames, remaining = extract_frames(frame)
        assert len(frames) == 1
        assert remaining == b""

    def test_extract_multiple_frames(self):
        from frame_codec import build_frame, extract_frames
        from protocol_const import OP_DEVBTN_TAIL
        f1 = build_frame(OP_ACK_READY)
        f2 = build_frame(OP_DEVBTN_TAIL)
        frames, remaining = extract_frames(f1 + f2)
        assert len(frames) == 2

    def test_extract_incomplete_frame_returned_as_remaining(self):
        from frame_codec import build_frame, extract_frames
        frame = build_frame(OP_ACK_READY)
        partial = frame[:3]
        frames, remaining = extract_frames(partial)
        assert len(frames) == 0
        assert remaining == partial

    def test_extract_frame_plus_partial(self):
        from frame_codec import build_frame, extract_frames
        f1 = build_frame(OP_ACK_READY)
        partial = bytes([0xA5, 0x5A, 0x00])
        frames, remaining = extract_frames(f1 + partial)
        assert len(frames) == 1
        assert remaining == partial

    def test_extract_empty_buffer(self):
        from frame_codec import extract_frames
        frames, remaining = extract_frames(b"")
        assert len(frames) == 0
        assert remaining == b""

    def test_extract_frame_with_leading_garbage(self):
        from frame_codec import build_frame, extract_frames
        frame = build_frame(OP_ACK_READY)
        buffer = b'\xDE\xAD' + frame
        frames, remaining = extract_frames(buffer)
        assert len(frames) == 1
        assert remaining == b""

    def test_extract_skips_corrupt_known_opcode_frame(self):
        from frame_codec import build_frame, extract_frames
        from protocol_const import OP_DEVBTN_TAIL
        corrupt = bytearray(build_frame(OP_ACK_READY))
        corrupt[-1] = (corrupt[-1] + 1) & 0xFF  # corrupt checksum
        valid = build_frame(OP_DEVBTN_TAIL)
        frames, remaining = extract_frames(bytes(corrupt) + valid)
        # Should recover and find the valid frame
        assert len(frames) >= 1


class TestExtractFramesFuzz:
    """Adversarial inputs: malformed streams must not IndexError, loop,
    or invent frame boundaries via greedy checksum scanning."""

    def test_lone_sync0_at_end(self):
        """A trailing 0xA5 with no SYNC1 must not crash — it's a stream boundary."""
        from frame_codec import extract_frames
        frames, remaining = extract_frames(b"\xA5")
        assert frames == []
        assert remaining == b"\xA5"

    def test_sync_pair_at_end_missing_opcode(self):
        """Sync pair with no room for opcode/checksum must be held for more data."""
        from frame_codec import extract_frames
        frames, remaining = extract_frames(b"\xA5\x5A")
        assert frames == []
        assert remaining == b"\xA5\x5A"

    def test_one_byte_partial_after_sync(self):
        """`A5 5A 00` — not enough bytes for MIN_FRAME_SIZE, must not IndexError."""
        from frame_codec import extract_frames
        frames, remaining = extract_frames(b"\xA5\x5A\x00")
        assert frames == []
        assert remaining == b"\xA5\x5A\x00"

    def test_sync_bytes_inside_payload_do_not_mis_frame(self):
        """A legitimate long frame containing 0xA5 0x5A mid-payload must not
        be chopped up at the inner sync bytes."""
        from frame_codec import build_frame, extract_frames
        from protocol_const import OP_CATALOG_ROW_DEVICE
        # 96-byte payload containing 0xA5 0x5A at offset 10
        payload = bytearray(96)
        payload[10] = 0xA5
        payload[11] = 0x5A
        frame = build_frame(OP_CATALOG_ROW_DEVICE, bytes(payload))
        frames, remaining = extract_frames(frame)
        assert len(frames) == 1
        assert remaining == b""

    def test_unknown_opcode_does_not_greedily_invent_frame(self):
        """When an opcode is not in the known-size table, we must advance
        past the sync and NOT synthesize a short frame from a coincidental
        checksum byte."""
        from frame_codec import extract_frames
        # Opcode 0x9999 is not in _KNOWN_FRAME_SIZES. Checksum byte 0x9B
        # would have matched the greedy algorithm for a 5-byte candidate:
        # sum(0xA5, 0x5A, 0x99, 0x99) & 0xFF = 0x91 — intentionally not
        # matching, but any 5..N byte span that accidentally balances must
        # never be returned.
        buf = bytes([0xA5, 0x5A, 0x99, 0x99, 0x91])
        frames, remaining = extract_frames(buf)
        assert frames == []  # Must not claim to have extracted anything.

    def test_unknown_opcode_does_not_hang_on_large_buffer(self):
        """Regression: the old greedy scan was O(N^2). Large buffers of
        unknown-opcode bytes must return quickly."""
        from frame_codec import extract_frames
        # 100KB starting with sync + unknown opcode + random-ish bytes.
        big = b"\xA5\x5A\x99\x99" + bytes(range(256)) * 400
        frames, remaining = extract_frames(big)
        # Must return — we don't care how much, just that it doesn't hang.
        assert isinstance(frames, list)

    def test_leading_garbage_then_unknown_then_known(self):
        """Garbage, then unknown opcode, then a real frame — we must
        recover the real frame by skipping past the unknown sync."""
        from frame_codec import build_frame, extract_frames
        valid = build_frame(OP_ACK_READY)
        buf = b"\xDE\xAD\xA5\x5A\x99\x99" + valid
        frames, remaining = extract_frames(buf)
        assert len(frames) == 1
