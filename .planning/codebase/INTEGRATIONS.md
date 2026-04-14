# INTEGRATIONS.md — External Integrations

## Overview

The plugin integrates with two distinct hardware protocols depending on hub
model. Both can operate simultaneously within a single plugin instance.

| Hub Model | Protocol | Transport | Discovery |
|-----------|---------|-----------|-----------|
| Sofabaton X2 | MQTT (JSON) | TCP to broker | `_sofabaton_hub._udp.local.` |
| Sofabaton X1 | Proprietary binary | Direct TCP (reverse-connect) | `_x1hub._udp.local.` |
| Sofabaton X1S | Proprietary binary | Direct TCP (reverse-connect) | `_x1hub._udp.local.` |

---

## X2 — MQTT Protocol

### Prerequisites

- An MQTT broker reachable from the Indigo Mac (Mosquitto, or the FlyingDiver
  MQTT Broker plugin for Indigo)
- Sofabaton X2 configured to connect to the broker via the Sofabaton app
  (Add Device → Home Assistant)

### Topic Structure

All topics use the hub's MAC address (12-char uppercase hex, no separators):

```
activity/{MAC}/<suffix>
device/{MAC}/<suffix>
```

### Subscribed Topics (hub → plugin)

| Topic | Payload | Trigger |
|-------|---------|---------|
| `activity/{mac}/list` | `{"data": [{activity_id, activity_name, state}, ...]}` | Response to list_request |
| `activity/{mac}/activity_control_up` | `{"activity_id": N, "state": "on"\|"off"}` | Activity state change |
| `activity/{mac}/keys_list` | `{"activity_id": N, "data": [{key_id, key_name?}, ...]}` | Assigned keys response |
| `activity/{mac}/macro_keys_list` | `{"activity_id": N, "data": [{key_id, key_name?}, ...]}` | Macro keys response |
| `activity/{mac}/favorites_keys_list` | `{"activity_id": N, "data": [{key_id, key_name?, device_id}, ...]}` | Favorite keys response |
| `device/{mac}/list` | `{"data": [{device_id, device_name}, ...]}` | Device list response |
| `device/{mac}/keys_list` | `{"device_id": N, "data": [...]}` | Device key list response |

### Published Topics (plugin → hub)

| Topic | Payload | Purpose |
|-------|---------|---------|
| `activity/{mac}/list_request` | `{"data": "activity_list"}` | Request activity list |
| `activity/{mac}/activity_control_down` | `{"data": {"activity_id": N, "state": "on"\|"off"}}` | Activate / deactivate activity |
| `activity/{mac}/keys_control` | `{"data": {"activity_id": N, "key_id": N}}` | Send hardware key press |
| `activity/{mac}/macro_keys_control` | `{"data": {"activity_id": N, "key_id": N}}` | Send macro key |
| `activity/{mac}/favorites_keys_control` | `{"data": {"activity_id": device_id, "key_id": N}}` | Send favorite key (see firmware quirk) |

### Special Values

- `activity_id = 255` in `activity_control_up` means all activities stopped
- `activity_id = 255` in `activity_control_down` with `state = "off"` stops
  all activities

### Hub Constraint

The X2 hub is single-threaded. A `PUBLISH_DELAY = 0.2` second sleep is
inserted after each MQTT publish to avoid overloading it.

### Firmware Quirk — Favorite Keys

When sending a favorite key, the `activity_id` field in the payload must
contain the `device_id`, not the actual activity ID. This is a known bug in
Sofabaton firmware. The plugin works around it in `_send_favorite_key()`.

### Hardware Key IDs (27 keys)

```
up=174, down=178, left=175, right=177, ok=176
back=179, home=180, menu=181
volume_up=182, volume_down=185, mute=184
channel_up=183, channel_down=186, guide=157
rewind=187, play=156, fast_forward=189
dvr=155, pause=188, exit=154
red=190, green=191, yellow=192, blue=193
a=153, b=152, c=151
```

---

## X1/X1S — TCP Binary Protocol

Protocol reverse-engineered from
[github.com/m3tac0de/home-assistant-sofabaton-x1s](https://github.com/m3tac0de/home-assistant-sofabaton-x1s).

### Connection Model (Reverse TCP)

The hub does **not** accept incoming connections. Instead:

1. Plugin opens a TCP server socket on port 8200 (range 8200–8231, first
   available)
2. Plugin sends UDP `CALL_ME` packets to `hub_ip:8102` every ~2 seconds
3. Hub connects back to the plugin's listening port
4. Once connected, plugin requests the device + activity catalog
5. TCP keepalives maintain the session (idle=30s, interval=10s, count=3)
6. On disconnect, plugin restarts the CALL_ME loop after 3 seconds

### Wire Format

Every frame:
```
[0xA5] [0x5A] [opcode_hi] [opcode_lo] [payload...] [checksum]
```

- Sync: `0xA5 0x5A` (2 bytes)
- Opcode: big-endian 16-bit
- Payload: variable length (0+ bytes)
- Checksum: `sum(all preceding bytes) & 0xFF`

Minimum frame size: 5 bytes (sync + opcode + checksum, no payload).

### CALL_ME UDP Packet

```
[0xA5] [0x5A] [0x00] [0x01] [0x00*6] [ip_bytes(4)] [port_bytes(2, big-endian)] [checksum]
```

Opcode `0x0001` = `OP_CALL_ME`. The 6 zero bytes are padding. IP and port
tell the hub where to connect back.

### Request Opcodes (plugin → hub)

| Constant | Value | Purpose |
|----------|-------|---------|
| `OP_CALL_ME` | `0x0001` | UDP: tell hub our callback address |
| `OP_REQ_DEVICES` | `0x000A` | Request device catalog |
| `OP_REQ_ACTIVITIES` | `0x003A` | Request activity catalog |
| `OP_REQ_BUTTONS` | `0x023C` | Send a device command |
| `OP_REQ_COMMANDS` | `0x025C` | Request commands for a device |
| `OP_REQ_ACTIVATE` | `0x023F` | Activate or deactivate activity |
| `OP_REQ_ACTIVITY_MAP` | `0x016C` | Request activity map |
| `OP_FIND_REMOTE` | `0x0023` | Find remote |
| `OP_REMOTE_SYNC` | `0x0064` | Remote sync |

### Response Opcodes (hub → plugin)

| Constant | Value | Purpose |
|----------|-------|---------|
| `OP_ACK_READY` | `0x0160` | Hub ready (no payload) |
| `OP_CATALOG_ROW_DEVICE` | `0xD50B` | X1S device row (96-byte payload) |
| `OP_CATALOG_ROW_ACTIVITY` | `0xD53B` | X1S activity row (96-byte payload) |
| `OP_X1_DEVICE` | `0x7B0B` | X1 device row (64-byte payload) |
| `OP_X1_ACTIVITY` | `0x7B3B` | X1 activity row (64-byte payload) |
| `OP_DEVBTN_HEADER` | `0xD95D` | Button catalog header |
| `OP_DEVBTN_PAGE` | `0xD55D` | Button catalog page |
| `OP_DEVBTN_SINGLE` | `0x4D5D` | Single button record |
| `OP_DEVBTN_TAIL` | `0x495D` | Button catalog end marker |

### X1 vs X1S Payload Differences

X1 and X1S use different catalog row layouts:

| Field | X1 | X1S |
|-------|----|-----|
| Device/Activity ID | bytes 2–4 (3 bytes, big-endian) | same |
| Active flag | byte 5 | byte 31 |
| Name encoding | UTF-8 at bytes 28–58 | UTF-16BE at bytes 32–92 |
| Name length | 30 bytes | 60 bytes |

Hub model is determined at mDNS discovery time via the `HVER` property
(`"1"` = X1, `"2"` = X1S). The `is_x1` flag is passed through to
`dispatch_opcode()` and the parser functions.

### Opcode Family Fallback

Unknown opcodes whose low byte matches a known family are dispatched to the
appropriate handler as a fallback:

| Family byte | Meaning |
|-------------|---------|
| `0x0B` | Device row |
| `0x3B` | Activity row |
| `0x5D` | Button/keymap data |

### Activate / Deactivate Payload

```
OP_REQ_ACTIVATE payload: [activity_id(4, big-endian)] [0x01=activate | 0x00=deactivate]
```

### Send Command Payload

```
OP_REQ_BUTTONS payload: [activity_id(4)] [device_id(1)] [command_id(1)] [control_block(7)]
```

`device_id` and `command_id` must be 0–255. `control_block` defaults to 7
zero bytes.
