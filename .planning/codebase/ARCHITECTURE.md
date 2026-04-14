# ARCHITECTURE.md — Plugin Architecture

## Overview

A single `Plugin` class manages both hub types simultaneously. MQTT
(X2) runs in a paho background thread; TCP (X1/X1S) runs in two daemon
threads managed by `TcpTransport`. A shared `_activities` dict (with
per-entry `_hub_dev_id` tagging) tracks activities from both transports.

---

## Plugin Lifecycle

```
__init__()         — read prefs, initialise instance vars (no I/O)
startup()          — find/create hub devices, start MQTT, start X1 transport
runConcurrentThread() — lightweight loop: prune dedup cache every 30 s
shutdown()         — stop MQTT, stop X1 transport
deviceStartComm()  — set hub device ref; reconnect MQTT if MAC changed;
                     start X1 transport if not already running
deviceStopComm()   — no-op beyond super() call
```

---

## Transport Layer

### X2 — MQTT (paho background thread)

```
_start_mqtt()        — create paho client, set callbacks, connect_async, loop_start
_stop_mqtt()         — loop_stop, disconnect
_on_connect()        — subscribe all topics; optionally request activity list
_on_disconnect()     — update hub state; paho auto-reconnects
_on_message()        — decode JSON, dedup check, dispatch to handler
_subscribe_all()     — subscribe to 7 activity/* and device/* topics
_publish()           — json.dumps, mqtt.publish, wait_for_publish, sleep(0.2)
```

### X1/X1S — TCP (`transport_tcp.TcpTransport`)

```
TcpTransport.connect()     — bind server socket, start callme thread
_callme_loop()             — send UDP CALL_ME every ~2 s until hub connects
_setup_connection()        — configure keepalives, start receive thread,
                             call _fetch_catalogs()
_receive_loop()            — select() + recv(4096), feed extract_frames(),
                             dispatch each frame via _process_frame()
_process_frame()           — parse_frame() → dispatch_opcode() → update
                             internal _devices/_activities, fire callbacks
_handle_disconnect()       — close sockets, fire callback, schedule _reconnect
_reconnect()               — re-bind listener, restart callme thread (3 s delay)
TcpTransport.disconnect()  — set _stopping, close sockets, join threads
```

Callbacks from `TcpTransport` into `Plugin`:

| Callback | When fired | Plugin handler |
|----------|-----------|----------------|
| `on_activity_update` | Each activity frame | `_on_x1_activity_update()` |
| `on_connection_change` | Connect / disconnect | `_on_x1_connection_change()` |

---

## Device Types

### `sofabatonHub` (custom)

Represents the X2 hub. One instance per plugin (auto-created in `startup()`
if absent). States: `connectionStatus` (string), `activeActivity` (string),
`activeActivityId` (int). Display state: `activeActivity`.

### `sofabatonX1Hub` (custom)

Represents an X1 or X1S hub. Created by mDNS discovery (`discoverHub()`
menu item). States: `connectionStatus`, `activeActivity`, `activeActivityId`,
`hubModel`, `deviceCount`. `allowUserCreation="false"` — only created
programmatically.

### `sofabatonActivity` (relay)

One device per activity, shared between hub types. `onOffState` is the
standard relay boolean. Auto-created in `_sync_activity_devices()` when the
plugin receives activity lists from either hub. `allowUserCreation="false"`.

Plugin props on activity devices:

| Prop | Type | Notes |
|------|------|-------|
| `activityId` | str(int) | Hub-assigned numeric activity ID |
| `activityName` | str | Display name from hub |
| `hubDevice` | str(int) | Indigo device ID of parent hub |

---

## Activity Tracking

`Plugin._activities` is a dict keyed by activity ID:

```python
{
    act_id: {
        "name": str,
        "state": "on" | "off",
        "_hub_dev_id": int,   # Indigo ID of owning hub device
    }
}
```

Protected by `_activities_lock` (threading.Lock). X2 and X1 activities coexist
in the same dict, distinguished by `_hub_dev_id`. On refresh, only activities
belonging to the refreshing hub are removed before re-adding.

---

## Command Dispatch

When an activity device is turned on/off via `actionControlDevice()`:

```
actionControlDevice()
  → _get_transport_for_activity()   — compare pluginProps.hubDevice to
                                      _x1_hub_dev_id → "x1" or "mqtt"
  → _send_activity_command()
      "x1"   → TcpTransport.activate() / deactivate()
      "mqtt"  → _send_activity_control() → _publish()
```

Custom action routing:

| Action | Transport |
|--------|-----------|
| `sendKeyPress` | MQTT only (`_send_key_control`) |
| `sendMacroKey` | MQTT only (`_send_macro_key`) |
| `sendFavoriteKey` | MQTT only (`_send_favorite_key`) |
| `sendKeyToCurrentActivity` | MQTT only |
| `sendDeviceCommand` | X1/X1S only (`TcpTransport.send_command`) |
| `refreshActivities` | MQTT list_request |
| `stopAllActivities` | MQTT activity_id=255 |

---

## Thread Safety

| Shared state | Protected by |
|-------------|-------------|
| `_activities` | `_activities_lock` |
| `_mqtt` client | paho's internal lock + `_mqtt_lock` (plugin-level) |
| MQTT publish | `_publish_lock` |
| TCP send | `TcpTransport._send_lock` |
| TCP recv buffer | single receive thread (no lock needed) |
| `TcpTransport._devices/_activities/_commands` | accessed only from receive thread; plugin reads copies via `@property` |

---

## mDNS Discovery

`discoverHub()` menu callback: creates a `Zeroconf` instance, browses
`_sofabaton_hub._udp.local.` and `_x1hub._udp.local.`, waits 3 seconds,
then calls `_create_discovered_hub()` for each result. Hub model is
determined from the `HVER` mDNS TXT record. X1/X1S hubs create a
`sofabatonX1Hub` device and immediately start the TCP transport.

---

## Dedup Cache

MQTT messages are deduplicated by topic: if the same `(topic, payload_hash)`
pair appears within 5 seconds, the second message is silently ignored. The
`runConcurrentThread` loop prunes expired entries every 30 seconds.

---

## Indigo State Updates

Hub state updates are centralised in helper methods:

| Helper | Updates |
|--------|---------|
| `_update_hub_connection(status)` | `connectionStatus`, state image |
| `_update_hub_active_activity(act_id)` | `activeActivity`, `activeActivityId` |
| `_update_all_activity_states()` | all `sofabatonActivity` `onOffState` |
| `_update_x1_hub_states(act_id)` | `activeActivity`, `activeActivityId`, `deviceCount` |
| `_on_x1_connection_change(status)` | X1 hub `connectionStatus`, image |
