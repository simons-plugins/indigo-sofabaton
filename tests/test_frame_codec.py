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
        f1 = build_frame(OP_REQ_DEVICES)
        f2 = build_frame(OP_REQ_ACTIVITIES)
        frames, remaining = extract_frames(f1 + f2)
        assert len(frames) == 2

    def test_extract_incomplete_frame_returned_as_remaining(self):
        from frame_codec import build_frame, extract_frames
        frame = build_frame(OP_REQ_DEVICES)
        partial = frame[:3]
        frames, remaining = extract_frames(partial)
        assert len(frames) == 0
        assert remaining == partial

    def test_extract_frame_plus_partial(self):
        from frame_codec import build_frame, extract_frames
        f1 = build_frame(OP_REQ_DEVICES)
        partial = bytes([0xA5, 0x5A, 0x00])
        frames, remaining = extract_frames(f1 + partial)
        assert len(frames) == 1
        assert remaining == partial

    def test_extract_empty_buffer(self):
        from frame_codec import extract_frames
        frames, remaining = extract_frames(b"")
        assert len(frames) == 0
        assert remaining == b""
