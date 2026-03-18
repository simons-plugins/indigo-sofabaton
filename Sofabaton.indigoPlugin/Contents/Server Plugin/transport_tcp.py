"""TCP transport for Sofabaton X1/X1S hubs.

Implements the reverse-connection protocol:
1. Open TCP server socket on local port
2. Send UDP CALL_ME packets to hub:8102
3. Hub connects back to our listening port
4. Bidirectional binary frame communication
"""
import random
import socket
import select
import struct
import threading
import time

from protocol_const import (
    OP_REQ_DEVICES, OP_REQ_ACTIVITIES, OP_REQ_ACTIVATE,
    OP_REQ_BUTTONS, OP_REQ_COMMANDS, OP_REQ_ACTIVITY_MAP,
    OP_ACK_READY,
    UDP_CALLME_PORT, TCP_BASE_PORT, TCP_PORT_RANGE,
    CALLME_INTERVAL, CALLME_JITTER, COMMAND_DELAY,
    TCP_KEEPALIVE_IDLE, TCP_KEEPALIVE_INTERVAL, TCP_KEEPALIVE_COUNT,
)
from frame_codec import build_frame, build_callme_packet, parse_frame, extract_frames
from opcode_handlers import dispatch_opcode


class TcpTransport:
    """Manages TCP connection to a Sofabaton X1/X1S hub."""

    def __init__(self, hub_ip, hub_mac, logger,
                 listen_port_base=TCP_BASE_PORT,
                 hub_model="X1S",
                 on_activity_update=None,
                 on_connection_change=None):
        self.hub_ip = hub_ip
        self.hub_mac = hub_mac
        self.logger = logger
        self.listen_port_base = listen_port_base
        self.hub_model = hub_model

        self._on_activity_update = on_activity_update
        self._on_connection_change = on_connection_change

        # Connection state
        self._socket = None
        self._server_socket = None
        self._connected = False
        self._stopping = False
        self._send_lock = threading.Lock()

        # Background threads
        self._callme_thread = None
        self._receive_thread = None

        # Receive buffer
        self._recv_buffer = b""

        # Cached catalogs
        self._devices = {}     # device_id -> {"name": str}
        self._activities = {}  # activity_id -> {"name": str, "active": bool}
        self._commands = {}    # device_id -> [{"command_id": int, "label": str}]

    # --- Public properties ---

    def is_connected(self):
        return self._connected

    @property
    def devices(self):
        return dict(self._devices)

    @property
    def activities(self):
        return dict(self._activities)

    @property
    def commands(self):
        return dict(self._commands)

    # --- Connection lifecycle ---

    def connect(self):
        """Start the connection process: listen + send CALL_ME packets."""
        if self._connected or self._callme_thread is not None:
            return

        self._stopping = False
        self._start_listener()
        self._callme_thread = threading.Thread(
            target=self._callme_loop, daemon=True, name="x1-callme"
        )
        self._callme_thread.start()

    def disconnect(self):
        """Stop all threads and close sockets."""
        self._stopping = True

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        self._connected = False
        self._callme_thread = None
        self._receive_thread = None
        self._recv_buffer = b""

        if self._on_connection_change:
            self._on_connection_change("disconnected")

    # --- Send methods ---

    def send_frame(self, opcode, payload=b""):
        """Send a binary frame to the hub. Returns True on success."""
        if not self._connected or not self._socket:
            return False

        frame = build_frame(opcode, payload)
        with self._send_lock:
            try:
                self._socket.sendall(frame)
                time.sleep(COMMAND_DELAY)
                return True
            except Exception as exc:
                self.logger.error("Send failed: %s" % exc)
                self._handle_disconnect()
                return False

    def request_activities(self):
        """Request the activity list from hub."""
        return self.send_frame(OP_REQ_ACTIVITIES)

    def request_devices(self):
        """Request the device list from hub."""
        return self.send_frame(OP_REQ_DEVICES)

    def request_commands(self, device_id):
        """Request the command list for a specific device."""
        payload = struct.pack(">I", device_id)
        return self.send_frame(OP_REQ_COMMANDS, payload)

    def activate(self, activity_id):
        """Activate an activity."""
        payload = struct.pack(">I", activity_id) + bytes([0x01])
        return self.send_frame(OP_REQ_ACTIVATE, payload)

    def deactivate(self, activity_id):
        """Deactivate an activity."""
        payload = struct.pack(">I", activity_id) + bytes([0x00])
        return self.send_frame(OP_REQ_ACTIVATE, payload)

    def send_command(self, activity_id, device_id, command_id, control_block=None):
        """Send a device command via the active activity."""
        if control_block is None:
            control_block = bytes(7)
        payload = (
            struct.pack(">I", activity_id)
            + bytes([device_id, command_id])
            + control_block
        )
        return self.send_frame(OP_REQ_BUTTONS, payload)

    # --- Internal: listener ---

    def _start_listener(self):
        """Open a TCP server socket on the first available port in range."""
        for offset in range(TCP_PORT_RANGE):
            port = self.listen_port_base + offset
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                sock.listen(1)
                sock.settimeout(2.0)
                self._server_socket = sock
                self._listen_port = port
                self.logger.info("Listening for X1 hub on port %d" % port)
                return
            except OSError:
                continue

        raise RuntimeError("No available port in range %d-%d" % (
            self.listen_port_base, self.listen_port_base + TCP_PORT_RANGE - 1
        ))

    # --- Internal: CALL_ME loop ---

    def _callme_loop(self):
        """Send UDP CALL_ME packets until hub connects or we're stopped."""
        local_ip = self._get_local_ip()
        self.logger.info("Sending CALL_ME to %s:%d (callback %s:%d)" % (
            self.hub_ip, UDP_CALLME_PORT, local_ip, self._listen_port
        ))

        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while not self._stopping and not self._connected:
                packet = build_callme_packet(local_ip, self._listen_port)
                try:
                    udp_sock.sendto(packet, (self.hub_ip, UDP_CALLME_PORT))
                except Exception as exc:
                    self.logger.debug("CALL_ME send error: %s" % exc)

                try:
                    conn, addr = self._server_socket.accept()
                    self.logger.info("Hub connected from %s:%d" % addr)
                    self._setup_connection(conn)
                    return
                except socket.timeout:
                    pass

                jitter = random.uniform(0, CALLME_JITTER)
                time.sleep(CALLME_INTERVAL - self._server_socket.gettimeout() + jitter)
        finally:
            udp_sock.close()

    def _setup_connection(self, conn):
        """Configure the accepted TCP connection and start receive thread."""
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            TCP_KEEPALIVE = getattr(socket, "TCP_KEEPALIVE", 0x10)
            conn.setsockopt(socket.IPPROTO_TCP, TCP_KEEPALIVE, TCP_KEEPALIVE_IDLE)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, TCP_KEEPALIVE_INTERVAL)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, TCP_KEEPALIVE_COUNT)
        except (AttributeError, OSError):
            pass

        self._socket = conn
        self._connected = True
        self._recv_buffer = b""

        if self._on_connection_change:
            self._on_connection_change("connected")

        self._receive_thread = threading.Thread(
            target=self._receive_loop, daemon=True, name="x1-receive"
        )
        self._receive_thread.start()

        self._fetch_catalogs()

    # --- Internal: receive loop ---

    def _receive_loop(self):
        """Read frames from the hub until disconnected."""
        while not self._stopping and self._connected:
            try:
                ready, _, _ = select.select([self._socket], [], [], 1.0)
                if not ready:
                    continue

                data = self._socket.recv(4096)
                if not data:
                    self.logger.info("Hub closed connection")
                    self._handle_disconnect()
                    return

                self._recv_buffer += data
                frames, self._recv_buffer = extract_frames(self._recv_buffer)

                for raw_frame in frames:
                    self._process_frame(raw_frame)

            except Exception as exc:
                if not self._stopping:
                    self.logger.error("Receive error: %s" % exc)
                    self._handle_disconnect()
                return

    def _process_frame(self, raw_frame):
        """Parse and dispatch a single received frame."""
        try:
            opcode, payload = parse_frame(raw_frame)
        except ValueError as exc:
            self.logger.debug("Frame parse error: %s" % exc)
            return

        is_x1 = self.hub_model == "X1"
        result = dispatch_opcode(opcode, payload, is_x1=is_x1)
        if result is None:
            self.logger.debug("Unknown opcode: 0x%04X" % opcode)
            return

        msg_type = result["type"]

        if msg_type == "ack_ready":
            self.logger.info("Hub ready")

        elif msg_type == "device":
            data = result["data"]
            self._devices[data["device_id"]] = {"name": data["name"]}
            self.logger.debug("Device: [%d] %s" % (data["device_id"], data["name"]))

        elif msg_type == "activity":
            data = result["data"]
            self._activities[data["activity_id"]] = {
                "name": data["name"],
                "active": data["active"],
            }
            self.logger.debug("Activity: [%d] %s (active=%s)" % (
                data["activity_id"], data["name"], data["active"]
            ))
            if self._on_activity_update:
                self._on_activity_update(self._activities)

        elif msg_type == "buttons_complete":
            self.logger.debug("Button catalog complete")

        elif msg_type == "button_data":
            self.logger.debug("Button data frame: 0x%04X" % result.get("opcode", 0))

    # --- Internal: catalog fetch ---

    def _fetch_catalogs(self):
        """Request device and activity catalogs from hub after connecting."""
        self.logger.info("Fetching device and activity catalogs...")
        self._devices.clear()
        self._activities.clear()
        self.request_devices()
        self.request_activities()

    # --- Internal: disconnect handling ---

    def _handle_disconnect(self):
        """Handle unexpected disconnection — clean up and attempt reconnect."""
        was_connected = self._connected
        self._connected = False

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if was_connected and not self._stopping:
            if self._on_connection_change:
                self._on_connection_change("disconnected")
            self.logger.info("Connection lost, will reconnect...")
            threading.Timer(3.0, self._reconnect).start()

    def _reconnect(self):
        """Restart the connection process."""
        if self._stopping:
            return
        self.logger.info("Reconnecting to X1 hub...")
        if self._server_socket is None:
            self._start_listener()
        self._callme_thread = threading.Thread(
            target=self._callme_loop, daemon=True, name="x1-callme"
        )
        self._callme_thread.start()

    # --- Internal: helpers ---

    def _get_local_ip(self):
        """Get our local IP address on the same network as the hub."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.hub_ip, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"
