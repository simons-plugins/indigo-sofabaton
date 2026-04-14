"""Sofabaton X1/X1S binary protocol constants.

Reference: github.com/m3tac0de/home-assistant-sofabaton-x1s
"""

# Frame sync bytes
SYNC0 = 0xA5
SYNC1 = 0x5A
MIN_FRAME_SIZE = 5  # sync(2) + opcode(2) + checksum(1)

# --- Request opcodes (client -> hub) ---
OP_CALL_ME = 0x0001
OP_REQ_DEVICES = 0x000A
OP_REQ_ACTIVITIES = 0x003A
OP_REQ_BUTTONS = 0x023C
OP_REQ_COMMANDS = 0x025C
OP_REQ_ACTIVATE = 0x023F
OP_REQ_ACTIVITY_MAP = 0x016C
OP_FIND_REMOTE = 0x0023
OP_REMOTE_SYNC = 0x0064

# --- Response opcodes (hub -> client) ---
OP_ACK_READY = 0x0160
OP_CATALOG_ROW_DEVICE = 0xD50B
OP_CATALOG_ROW_ACTIVITY = 0xD53B
OP_X1_DEVICE = 0x7B0B
OP_X1_ACTIVITY = 0x7B3B
OP_DEVBTN_HEADER = 0xD95D
OP_DEVBTN_PAGE = 0xD55D
OP_DEVBTN_SINGLE = 0x4D5D
OP_DEVBTN_TAIL = 0x495D

# --- Opcode families (low byte identifies family) ---
FAMILY_DEV_ROW = 0x0B
FAMILY_ACT_ROW = 0x3B
FAMILY_MACROS = 0x13
FAMILY_KEYMAP = 0x3D
FAMILY_DEVBTNS = 0x5D

# --- Networking ---
UDP_CALLME_PORT = 8102
TCP_BASE_PORT = 8200
TCP_PORT_RANGE = 32  # ports 8200-8231
CALLME_INTERVAL = 2.0  # seconds between CALL_ME packets
CALLME_JITTER = 0.25  # random jitter added to interval
COMMAND_DELAY = 0.2  # minimum delay between commands

# --- TCP keepalive ---
TCP_KEEPALIVE_IDLE = 30
TCP_KEEPALIVE_INTERVAL = 10
TCP_KEEPALIVE_COUNT = 3

# --- Hub version classification (from HVER mDNS property) ---
HUB_VERSIONS = {
    "1": "X1",
    "2": "X1S",
    "3": "X2",
}

# --- mDNS service types ---
MDNS_X1 = "_x1hub._udp.local."
MDNS_X2 = "_sofabaton_hub._udp.local."
