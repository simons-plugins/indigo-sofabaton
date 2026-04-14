"""Tests for X1/X1S TCP transport."""
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

SERVER_PLUGIN_DIR = (
    Path(__file__).parent.parent
    / "Sofabaton.indigoPlugin"
    / "Contents"
    / "Server Plugin"
)
sys.path.insert(0, str(SERVER_PLUGIN_DIR))

from protocol_const import (
    OP_REQ_DEVICES, OP_REQ_ACTIVITIES, OP_REQ_ACTIVATE,
    UDP_CALLME_PORT, TCP_BASE_PORT,
)
from frame_codec import build_frame


class TestTcpTransportInit:
    def test_initial_state(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.hub_ip == "192.168.1.50"
        assert t.hub_mac == "AABBCCDDEEFF"
        assert t.is_connected() is False

    def test_default_port(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.listen_port_base == TCP_BASE_PORT

    def test_custom_port(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
            listen_port_base=9000,
        )
        assert t.listen_port_base == 9000

    def test_hub_model_default(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.hub_model == "X1S"

    def test_hub_model_x1(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
            hub_model="X1",
        )
        assert t.hub_model == "X1"


class TestTcpTransportCallbacks:
    def test_on_activity_update_callback(self):
        from transport_tcp import TcpTransport
        cb = Mock()
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
            on_activity_update=cb,
        )
        assert t._on_activity_update == cb

    def test_on_connection_change_callback(self):
        from transport_tcp import TcpTransport
        cb = Mock()
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
            on_connection_change=cb,
        )
        assert t._on_connection_change == cb


class TestTcpTransportSendFrame:
    def test_send_frame_when_not_connected(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        result = t.send_frame(OP_REQ_DEVICES)
        assert result is False

    def test_send_frame_when_connected(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        result = t.send_frame(OP_REQ_DEVICES)
        assert result is True
        t._socket.sendall.assert_called_once()

    def test_send_frame_with_payload(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        payload = bytes([0x01, 0x02])
        t.send_frame(OP_REQ_DEVICES, payload)
        sent_data = t._socket.sendall.call_args[0][0]
        assert sent_data[0] == 0xA5
        assert sent_data[1] == 0x5A


class TestTcpTransportHighLevelCommands:
    def test_request_activities(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.request_activities()
        t._socket.sendall.assert_called_once()

    def test_request_devices(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.request_devices()
        t._socket.sendall.assert_called_once()

    def test_activate_sends_exact_wire_bytes(self):
        """activate(101) must produce OP_REQ_ACTIVATE + be(101) + 0x01 byte."""
        import struct
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.activate(101)
        expected = build_frame(OP_REQ_ACTIVATE, struct.pack(">I", 101) + b"\x01")
        t._socket.sendall.assert_called_once_with(expected)

    def test_deactivate_sends_exact_wire_bytes(self):
        """deactivate(101) must produce OP_REQ_ACTIVATE + be(101) + 0x00 byte.

        Regression guard: activate and deactivate must NOT be byte-identical.
        """
        import struct
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.deactivate(101)
        expected = build_frame(OP_REQ_ACTIVATE, struct.pack(">I", 101) + b"\x00")
        t._socket.sendall.assert_called_once_with(expected)

    def test_activate_and_deactivate_differ(self):
        """Byte-level guard: their final payload byte must differ."""
        import struct
        a = build_frame(OP_REQ_ACTIVATE, struct.pack(">I", 101) + b"\x01")
        d = build_frame(OP_REQ_ACTIVATE, struct.pack(">I", 101) + b"\x00")
        assert a != d
        assert a[-2] != d[-2]  # the flag byte before the checksum


class TestTcpTransportCatalog:
    def test_devices_property_empty_initially(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.devices == {}

    def test_activities_property_empty_initially(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.activities == {}

    def test_commands_property_empty_initially(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        assert t.commands == {}


class TestSendCommandValidation:
    def test_rejects_device_id_over_255(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._socket = MagicMock()
        t._connected = True
        result = t.send_command(activity_id=1, device_id=256, command_id=0)
        assert result is False

    def test_rejects_negative_command_id(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._socket = MagicMock()
        t._connected = True
        result = t.send_command(activity_id=1, device_id=0, command_id=-1)
        assert result is False

    def test_accepts_valid_ids(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._socket = MagicMock()
        t._connected = True
        result = t.send_command(activity_id=101, device_id=5, command_id=1)
        assert result is True


class TestSendFrameErrorHandling:
    def test_socket_error_triggers_disconnect(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._socket = MagicMock()
        t._socket.sendall.side_effect = OSError("Connection reset")
        t._connected = True
        t._stopping = True  # prevent _handle_disconnect from arming reconnect
        result = t.send_frame(0x000A)
        assert result is False
        assert t._connected is False


class TestSendCommandControlBlockLength:
    def test_rejects_wrong_length_control_block(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._socket = MagicMock()
        t._connected = True
        # 20-byte control block would silently corrupt the frame.
        result = t.send_command(
            activity_id=1, device_id=1, command_id=1, control_block=bytes(20)
        )
        assert result is False
        t._socket.sendall.assert_not_called()


class TestReceiveLoopFragmentedReads:
    """Regression: a bug in the receive buffer would only show up when the
    kernel hands us a frame split across multiple recv() calls."""

    def test_receive_loop_handles_byte_at_a_time(self):
        """Feed a catalog-row frame one byte per recv() call and assert the
        activity callback fires exactly once with the parsed activity."""
        from transport_tcp import TcpTransport
        from protocol_const import OP_X1_ACTIVITY

        # Build a minimal X1 activity row (64-byte payload).
        payload = bytearray(64)
        # device_id at payload[2..4] — actually activity_id for activity rows.
        payload[2] = 0x00
        payload[3] = 0x00
        payload[4] = 0x0A  # activity_id = 10
        payload[5] = 0x01  # active flag (X1 layout)
        # name UTF-8 at [28:58]
        name = b"Watch TV"
        payload[28:28 + len(name)] = name
        frame = build_frame(OP_X1_ACTIVITY, bytes(payload))

        cb = Mock()
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
            hub_model="X1",
            on_activity_update=cb,
        )

        # Fake socket that returns the frame one byte at a time, then EOF.
        recv_queue = [bytes([b]) for b in frame] + [b""]
        fake_sock = MagicMock()
        fake_sock.recv.side_effect = recv_queue

        t._socket = fake_sock
        t._connected = True

        # Always "ready" until EOF forces the loop to return.
        with patch("transport_tcp.select.select",
                   return_value=([fake_sock], [], [])):
            t._receive_loop()

        # Activity callback must have fired exactly once with our parsed row.
        assert cb.call_count == 1
        activities = cb.call_args[0][0]
        assert 10 in activities
        assert activities[10]["name"] == "Watch TV"
        assert activities[10]["active"] is True


class TestReconnectOnListenerBindFailure:
    """When _start_listener raises on reconnect, we must back off and
    not spawn a duplicate callme thread."""

    def test_listener_bind_failure_reschedules_and_no_duplicate_thread(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())

        # Pretend there was a prior connection so _reconnect re-creates the listener.
        t._server_socket = None
        t._callme_thread = None
        t._reconnect_attempts = 0

        timers_started = []

        original_timer = threading.Timer

        def fake_timer(delay, fn, *a, **k):
            timer = original_timer(delay, lambda: None)  # never fires
            timers_started.append((delay, fn))
            return timer

        with patch.object(t, "_start_listener",
                          side_effect=RuntimeError("no ports")), \
             patch("transport_tcp.threading.Timer", side_effect=fake_timer):
            t._reconnect()

        # A new Timer must have been armed.
        assert len(timers_started) == 1
        delay, fn = timers_started[0]
        assert delay > 0
        # It must be re-entering _reconnect, not leaking a callme thread.
        assert fn == t._reconnect
        assert t._callme_thread is None

    def test_reconnect_respects_stopping(self):
        """If stopping flips between check and Timer arming, nothing schedules."""
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())
        t._stopping = True
        t._reconnect()  # must not raise or start anything
        assert t._callme_thread is None


class TestDisconnectCancelsReconnectTimer:
    """disconnect() must cancel any pending reconnect timer so no zombie
    callme thread spawns after shutdown."""

    def test_disconnect_cancels_pending_reconnect(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())

        fake_timer = MagicMock()
        t._reconnect_timer = fake_timer

        t.disconnect()

        fake_timer.cancel.assert_called_once()
        assert t._reconnect_timer is None


class TestGetLocalIpRaisesOnFailure:
    def test_get_local_ip_raises_instead_of_returning_0_0_0_0(self):
        """Regression: previously returned 0.0.0.0 silently, making the hub
        try to connect back to 0.0.0.0 and fail mysteriously."""
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())

        with patch("transport_tcp.socket.socket") as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = OSError("network unreachable")
            mock_sock_class.return_value = mock_sock

            import pytest
            with pytest.raises(OSError):
                t._get_local_ip()


class TestReceiveLoopExceptionSafety:
    """The receive loop must surface tracebacks for programming errors
    but must not die from a single bad dispatch."""

    def test_dispatch_exception_does_not_kill_loop(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())

        # Two valid frames back-to-back.
        from protocol_const import OP_ACK_READY
        frame = build_frame(OP_ACK_READY)
        data = frame + frame + b""

        fake_sock = MagicMock()
        fake_sock.recv.side_effect = [data, b""]
        t._socket = fake_sock
        t._connected = True

        call_count = [0]

        def crashing_dispatch(*a, **k):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated bug")
            return {"type": "ack_ready"}

        with patch("transport_tcp.dispatch_opcode", side_effect=crashing_dispatch), \
             patch("transport_tcp.select.select",
                   return_value=([fake_sock], [], [])):
            t._receive_loop()

        # Both frames were attempted — the first crash did not kill the loop.
        assert call_count[0] == 2
        # logger.exception must have been called for the traceback.
        assert t.logger.exception.called


class TestConcurrentCatalogAccess:
    """_state_lock must make catalog property access safe under concurrent
    mutation from the receive thread."""

    def test_activities_property_returns_snapshot_under_concurrent_mutation(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(hub_ip="192.168.1.50", hub_mac="AABBCCDDEEFF", logger=Mock())

        stop = threading.Event()
        errors = []

        def writer():
            i = 0
            while not stop.is_set():
                with t._state_lock:
                    t._activities[i] = {"name": "a%d" % i, "active": False}
                    if i > 50 and (i - 50) in t._activities:
                        del t._activities[i - 50]
                i += 1

        def reader():
            try:
                while not stop.is_set():
                    _ = t.activities  # must not raise
            except Exception as exc:
                errors.append(exc)

        w = threading.Thread(target=writer, daemon=True)
        r = threading.Thread(target=reader, daemon=True)
        w.start(); r.start()
        time.sleep(0.1)
        stop.set()
        w.join(timeout=1.0); r.join(timeout=1.0)

        assert errors == []
