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


# Reconnect backoff: start at 3s, cap at 60s, reset after a successful connect.
_RECONNECT_BACKOFF_BASE = 3.0
_RECONNECT_BACKOFF_MAX = 60.0

# Escalate CALL_ME send failures to a user-visible warning after this many
# consecutive failures (~N * CALLME_INTERVAL seconds of silence).
_CALLME_WARN_AFTER = 5

# Rate-limit frame-parse errors to a warning after this many consecutive bad frames.
_PARSE_ERROR_WARN_AFTER = 5


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
        self._listen_port = None
        self._connected = False
        self._stopping = False
        self._send_lock = threading.Lock()
        self._last_send_ts = 0.0

        # Protects _devices/_activities/_commands against cross-thread access.
        # Writes happen on the receive thread; reads happen on the main thread
        # via the property accessors and via _fetch_catalogs()'s .clear().
        self._state_lock = threading.Lock()

        # Guards concurrent _handle_disconnect() calls from send + receive threads.
        self._disconnect_lock = threading.Lock()

        # Background threads
        self._callme_thread = None
        self._receive_thread = None
        self._reconnect_timer = None
        self._reconnect_attempts = 0

        # Receive buffer
        self._recv_buffer = b""

        # Unknown-opcode rate limiting so new firmware is noticed once.
        self._unknown_opcodes_seen = set()
        self._parse_error_streak = 0

        # Cached catalogs
        self._devices = {}     # device_id -> {"name": str}
        self._activities = {}  # activity_id -> {"name": str, "active": bool}
        self._commands = {}    # device_id -> [{"command_id": int, "label": str}]

    # --- Public properties ---

    def is_connected(self):
        return self._connected

    @property
    def devices(self):
        with self._state_lock:
            return dict(self._devices)

    @property
    def activities(self):
        with self._state_lock:
            return dict(self._activities)

    @property
    def commands(self):
        with self._state_lock:
            return dict(self._commands)

    # --- Connection lifecycle ---

    def connect(self):
        """Start the connection process: listen + send CALL_ME packets."""
        if self._connected or self._callme_thread is not None:
            return

        self._stopping = False
        self._reconnect_attempts = 0
        self._start_listener()
        self._callme_thread = threading.Thread(
            target=self._callme_loop, daemon=True, name="x1-callme"
        )
        self._callme_thread.start()

    def disconnect(self):
        """Stop all threads and close sockets."""
        self._stopping = True

        # Cancel any pending reconnect timer before it can arm a fresh callme loop.
        timer = self._reconnect_timer
        self._reconnect_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

        if self._socket:
            try:
                self._socket.close()
            except OSError as exc:
                self.logger.debug("Error closing client socket: %s" % exc)
            self._socket = None

        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError as exc:
                self.logger.debug("Error closing server socket: %s" % exc)
            self._server_socket = None

        self._connected = False

        # Wait for threads to actually exit before clearing references
        if self._callme_thread and self._callme_thread.is_alive():
            self._callme_thread.join(timeout=5.0)
        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=5.0)
        self._callme_thread = None
        self._receive_thread = None
        self._recv_buffer = b""

        if self._on_connection_change:
            self._on_connection_change("disconnected")

    # --- Send methods ---

    def send_frame(self, opcode, payload=b""):
        """Send a binary frame to the hub. Returns True on success.

        Enforces a COMMAND_DELAY between sends via a last-send timestamp
        so we can interrupt the delay on shutdown without holding _send_lock
        across the sleep.
        """
        if not self._connected or not self._socket:
            return False

        frame = build_frame(opcode, payload)

        # Compute how long we still need to wait for the hub's single-threaded
        # rate limit, then sleep OUTSIDE the lock so disconnect() is not blocked.
        with self._send_lock:
            now = time.monotonic()
            wait = max(0.0, self._last_send_ts + COMMAND_DELAY - now)

        if wait > 0:
            # Poll _stopping so disconnect cuts through the pacing delay.
            deadline = time.monotonic() + wait
            while not self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.05))
            if self._stopping:
                return False

        sock = self._socket
        if sock is None:
            return False

        with self._send_lock:
            try:
                sock.sendall(frame)
                self._last_send_ts = time.monotonic()
                return True
            except OSError as exc:
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
        if not (0 <= device_id <= 255):
            self.logger.error("Device ID %d out of range (0-255)" % device_id)
            return False
        if not (0 <= command_id <= 255):
            self.logger.error("Command ID %d out of range (0-255)" % command_id)
            return False
        if control_block is None:
            control_block = bytes(7)
        if len(control_block) != 7:
            self.logger.error("Control block must be 7 bytes, got %d" % len(control_block))
            return False
        payload = (
            struct.pack(">I", activity_id)
            + bytes([device_id, command_id])
            + control_block
        )
        return self.send_frame(OP_REQ_BUTTONS, payload)

    # --- Internal: listener ---

    def _start_listener(self):
        """Open a TCP server socket on the first available port in range."""
        last_exc = None
        for offset in range(TCP_PORT_RANGE):
            port = self.listen_port_base + offset
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                sock.listen(1)
                sock.settimeout(2.0)
            except OSError as exc:
                last_exc = exc
                self.logger.debug("Port %d unavailable: %s" % (port, exc))
                try:
                    sock.close()
                except OSError:
                    pass
                continue
            self._server_socket = sock
            self._listen_port = port
            self.logger.info("Listening for X1 hub on port %d" % port)
            return

        raise RuntimeError(
            "No available port in range %d-%d (last error: %s)" % (
                self.listen_port_base,
                self.listen_port_base + TCP_PORT_RANGE - 1,
                last_exc,
            )
        )

    # --- Internal: CALL_ME loop ---

    def _callme_loop(self):
        """Send UDP CALL_ME packets until hub connects or we're stopped."""
        try:
            local_ip = self._get_local_ip()
        except OSError as exc:
            self.logger.error(
                "Cannot determine local IP for X1 hub at %s — check network: %s" % (
                    self.hub_ip, exc
                )
            )
            return

        # Capture the server socket locally so we don't dereference
        # self._server_socket after disconnect() has nil'd it.
        server_sock = self._server_socket
        if server_sock is None:
            return

        self.logger.info("Sending CALL_ME to %s:%d (callback %s:%d)" % (
            self.hub_ip, UDP_CALLME_PORT, local_ip, self._listen_port
        ))

        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        consecutive_send_errors = 0
        send_error_warned = False
        try:
            while not self._stopping and not self._connected:
                loop_start = time.monotonic()

                packet = build_callme_packet(local_ip, self._listen_port)
                try:
                    udp_sock.sendto(packet, (self.hub_ip, UDP_CALLME_PORT))
                    if consecutive_send_errors and send_error_warned:
                        self.logger.info("CALL_ME send recovered")
                    consecutive_send_errors = 0
                    send_error_warned = False
                except (OSError, socket.gaierror) as exc:
                    consecutive_send_errors += 1
                    if consecutive_send_errors == 1:
                        self.logger.warning(
                            "CALL_ME send to %s:%d failed: %s" % (
                                self.hub_ip, UDP_CALLME_PORT, exc
                            )
                        )
                    elif (consecutive_send_errors >= _CALLME_WARN_AFTER
                          and not send_error_warned):
                        self.logger.error(
                            "X1 hub unreachable at %s after %d CALL_ME attempts — "
                            "check IP address, network, and firewall (%s)" % (
                                self.hub_ip, consecutive_send_errors, exc
                            )
                        )
                        send_error_warned = True

                try:
                    conn, addr = server_sock.accept()
                    self.logger.info("Hub connected from %s:%d" % addr)
                    self._setup_connection(conn)
                    return
                except socket.timeout:
                    pass
                except OSError as exc:
                    # server socket was closed by disconnect() or _handle_disconnect()
                    if self._stopping:
                        return
                    self.logger.debug("Listener accept error: %s" % exc)
                    return

                elapsed = time.monotonic() - loop_start
                jitter = random.uniform(0, CALLME_JITTER)
                remaining = max(0, CALLME_INTERVAL - elapsed + jitter)
                if remaining > 0:
                    # Split the sleep so shutdown wakes us up quickly.
                    deadline = time.monotonic() + remaining
                    while not self._stopping and not self._connected:
                        now = time.monotonic()
                        if now >= deadline:
                            break
                        time.sleep(min(deadline - now, 0.1))
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
        except (AttributeError, OSError) as exc:
            self.logger.warning(
                "TCP keepalive unavailable — stale connections may not be "
                "detected: %s" % exc
            )

        self._socket = conn
        self._connected = True
        self._recv_buffer = b""
        self._reconnect_attempts = 0
        self._parse_error_streak = 0

        if self._on_connection_change:
            self._on_connection_change("connected")

        self._receive_thread = threading.Thread(
            target=self._receive_loop, daemon=True, name="x1-receive"
        )
        self._receive_thread.start()

        self._fetch_catalogs()

    # --- Internal: receive loop ---

    def _receive_loop(self):
        """Read frames from the hub until disconnected.

        Captures a local reference to the socket at loop entry so that
        disconnect() nil'ing self._socket mid-loop produces a clean
        OSError rather than an AttributeError.
        """
        sock = self._socket
        if sock is None:
            return

        while not self._stopping and self._connected:
            try:
                ready, _, _ = select.select([sock], [], [], 1.0)
            except (OSError, ValueError) as exc:
                # ValueError: select on closed fd. OSError: socket torn down.
                if not self._stopping:
                    self.logger.debug("Receive select error: %s" % exc)
                    self._handle_disconnect()
                return

            if not ready:
                continue

            try:
                data = sock.recv(4096)
            except OSError as exc:
                if not self._stopping:
                    self.logger.error("Receive read error: %s" % exc)
                    self._handle_disconnect()
                return

            if not data:
                if not self._stopping:
                    self.logger.info("Hub closed connection")
                    self._handle_disconnect()
                return

            self._recv_buffer += data
            try:
                frames, self._recv_buffer = extract_frames(self._recv_buffer)
            except Exception as exc:
                # Any bug inside the codec must be visible, not buried.
                self.logger.exception(
                    "Frame extraction crashed — dropping buffer: %s" % exc
                )
                self._recv_buffer = b""
                continue

            for raw_frame in frames:
                try:
                    self._process_frame(raw_frame)
                except Exception as exc:
                    # Programming errors in dispatch must surface with a traceback
                    # but must not kill the receive loop.
                    self.logger.exception(
                        "Frame dispatch crashed for opcode — continuing: %s" % exc
                    )

    def _process_frame(self, raw_frame):
        """Parse and dispatch a single received frame."""
        try:
            opcode, payload = parse_frame(raw_frame)
        except ValueError as exc:
            self._parse_error_streak += 1
            if self._parse_error_streak == _PARSE_ERROR_WARN_AFTER:
                self.logger.warning(
                    "Repeated frame parse errors (%d in a row): %s — "
                    "possible protocol mismatch or wire corruption" % (
                        self._parse_error_streak, exc
                    )
                )
            else:
                self.logger.debug("Frame parse error: %s" % exc)
            return

        self._parse_error_streak = 0

        is_x1 = self.hub_model == "X1"
        result = dispatch_opcode(opcode, payload, is_x1=is_x1)
        if result is None:
            if opcode not in self._unknown_opcodes_seen:
                self._unknown_opcodes_seen.add(opcode)
                self.logger.info(
                    "Unknown opcode 0x%04X from hub — firmware may have new features" % opcode
                )
            else:
                self.logger.debug("Unknown opcode (repeat): 0x%04X" % opcode)
            return

        msg_type = result["type"]

        if msg_type == "ack_ready":
            self.logger.info("Hub ready")

        elif msg_type == "device":
            data = result["data"]
            with self._state_lock:
                self._devices[data["device_id"]] = {"name": data["name"]}
            self.logger.debug("Device: [%d] %s" % (data["device_id"], data["name"]))

        elif msg_type == "activity":
            data = result["data"]
            with self._state_lock:
                self._activities[data["activity_id"]] = {
                    "name": data["name"],
                    "active": data["active"],
                }
                activities_snapshot = dict(self._activities)
            self.logger.debug("Activity: [%d] %s (active=%s)" % (
                data["activity_id"], data["name"], data["active"]
            ))
            if self._on_activity_update:
                self._on_activity_update(activities_snapshot)

        elif msg_type == "buttons_complete":
            self.logger.debug("Button catalog complete")

        elif msg_type == "button_data":
            self.logger.debug("Button data frame: 0x%04X" % result.get("opcode", 0))

    # --- Internal: catalog fetch ---

    def _fetch_catalogs(self):
        """Request device and activity catalogs from hub after connecting."""
        self.logger.info("Fetching device and activity catalogs...")
        with self._state_lock:
            self._devices.clear()
            self._activities.clear()
        self.request_devices()
        self.request_activities()

    # --- Internal: disconnect handling ---

    def _handle_disconnect(self):
        """Handle unexpected disconnection — clean up and attempt reconnect.

        Re-entrancy safe: serialized on _disconnect_lock so a send-thread
        error and a receive-thread error cannot both arm reconnect timers.
        """
        with self._disconnect_lock:
            was_connected = self._connected
            self._connected = False

            if self._socket:
                try:
                    self._socket.close()
                except OSError as exc:
                    self.logger.debug("Error closing socket on disconnect: %s" % exc)
                self._socket = None

            # Close the server socket so _reconnect creates a fresh listener
            if self._server_socket:
                try:
                    self._server_socket.close()
                except OSError as exc:
                    self.logger.debug("Error closing server socket on disconnect: %s" % exc)
                self._server_socket = None

            if self._stopping:
                return
            if not was_connected:
                return

            if self._on_connection_change:
                self._on_connection_change("disconnected")

            self._reconnect_attempts += 1
            delay = min(
                _RECONNECT_BACKOFF_MAX,
                _RECONNECT_BACKOFF_BASE * (2 ** (self._reconnect_attempts - 1)),
            )
            if self._reconnect_attempts == 1:
                self.logger.info("Connection lost, reconnecting in %.0fs..." % delay)
            elif self._reconnect_attempts <= 3:
                self.logger.warning(
                    "Connection lost (attempt %d), reconnecting in %.0fs..." % (
                        self._reconnect_attempts, delay
                    )
                )
            else:
                self.logger.error(
                    "Connection lost (attempt %d) — hub may be offline or "
                    "rejecting us. Reconnecting in %.0fs..." % (
                        self._reconnect_attempts, delay
                    )
                )

            # Cancel any pre-existing timer before arming a new one.
            old_timer = self._reconnect_timer
            if old_timer is not None:
                try:
                    old_timer.cancel()
                except Exception:
                    pass

            if self._stopping:
                return
            timer = threading.Timer(delay, self._reconnect)
            timer.daemon = True
            self._reconnect_timer = timer
            timer.start()

    def _reconnect(self):
        """Restart the connection process."""
        # The timer ran — clear the reference so disconnect() doesn't chase a stale one.
        self._reconnect_timer = None
        if self._stopping:
            return

        self.logger.info("Reconnecting to X1 hub...")

        if self._server_socket is None:
            try:
                self._start_listener()
            except RuntimeError as exc:
                self.logger.error("Cannot bind listener for reconnect: %s" % exc)
                if self._stopping:
                    return
                # Back off and try again.
                self._reconnect_attempts += 1
                delay = min(
                    _RECONNECT_BACKOFF_MAX,
                    _RECONNECT_BACKOFF_BASE * (2 ** (self._reconnect_attempts - 1)),
                )
                timer = threading.Timer(delay, self._reconnect)
                timer.daemon = True
                self._reconnect_timer = timer
                timer.start()
                return

        # Don't start a new callme thread if a previous one is still alive
        # (e.g. _handle_disconnect fired twice in quick succession).
        if self._callme_thread is not None and self._callme_thread.is_alive():
            return
        if self._stopping:
            return
        self._callme_thread = threading.Thread(
            target=self._callme_loop, daemon=True, name="x1-callme"
        )
        self._callme_thread.start()

    # --- Internal: helpers ---

    def _get_local_ip(self):
        """Get our local IP address on the same network as the hub.

        Raises OSError if the local address cannot be determined. The caller
        is responsible for surfacing a user-visible error — we deliberately
        do NOT fall back to 0.0.0.0 because the hub would then try to connect
        back to 0.0.0.0 and fail mysteriously.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((self.hub_ip, 80))
            return s.getsockname()[0]
        finally:
            try:
                s.close()
            except OSError:
                pass
