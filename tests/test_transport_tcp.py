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

    def test_activate(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.activate(101)
        t._socket.sendall.assert_called_once()

    def test_deactivate(self):
        from transport_tcp import TcpTransport
        t = TcpTransport(
            hub_ip="192.168.1.50",
            hub_mac="AABBCCDDEEFF",
            logger=Mock(),
        )
        t._socket = MagicMock()
        t._connected = True
        t.deactivate(101)
        t._socket.sendall.assert_called_once()


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
        result = t.send_frame(0x000A)
        assert result is False
        assert t._connected is False
