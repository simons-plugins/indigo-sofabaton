# CONCERNS.md — Tech Debt, Protocol Quirks, and TODOs

## Firmware / Protocol Quirks

### Favorite Key Firmware Bug

When sending a favorite key via MQTT, the `activity_id` field in the
`favorites_keys_control` payload must contain the `device_id`, not the
actual activity ID. This is a documented Sofabaton firmware design issue.
The workaround is in `_send_favorite_key()`:

```python
# Firmware quirk: activity_id field must contain device_id for favorites
return self._publish(topic, {"data": {"activity_id": device_id, "key_id": key_id}})
```

If Sofabaton ever fixes this firmware behaviour, this method will silently
break. There is no version guard.

### X1 vs X1S Payload Layout Differences

X1 and X1S use different byte offsets for the active flag and different string
encodings (UTF-8 vs UTF-16BE) in catalog row payloads. The distinction is
made via a boolean `is_x1` flag threaded through `dispatch_opcode()` and the
parser functions. The flag is set from `hub_model == "X1"`, which is read
from a plugin prop populated at discovery time. If a hub is added manually
(not via mDNS), `hubModel` defaults to `"X1S"` in the UI — this could cause
incorrect name parsing for an actual X1.

### Opcode Family Fallback

`dispatch_opcode()` falls back to matching the low byte of unknown opcodes
against known families. This is a heuristic: a future hub firmware could
introduce an opcode whose low byte collides with a family byte but means
something different. Unknown opcodes are logged at debug but silently dropped.

### Checksum-Scan Ambiguity

`extract_frames()` uses opcode-based known frame sizes for deterministic
parsing on common opcodes. For unknown opcodes it falls back to greedy
checksum scanning, which can produce false positive matches if random bytes
happen to satisfy the checksum condition. This is a known limitation noted in
the code comments.

---

## Architecture Concerns

### MQTT Transport Still Embedded in `plugin.py`

The design doc (`docs/plans/2026-03-18-x1-support-design.md`) describes a
planned `MqttTransport` class to mirror `TcpTransport`. This was not
implemented — all MQTT logic remains embedded in `Plugin`. This makes
`plugin.py` large (~960 lines) and harder to unit test the MQTT path in
isolation. The `TcpTransport` was cleanly extracted; MQTT was not.

### Single X1 Hub Limit

`startup()` and `deviceStartComm()` only find and start the first
`sofabatonX1Hub` device:

```python
for dev in indigo.devices.iter("self.sofabatonX1Hub"):
    self._x1_hub_dev_id = dev.id
    self._start_x1_transport(dev)
    break  # only the first
```

A user with multiple X1/X1S hubs will only see the first one work.
`_x1_transport` is a single reference, not a dict.

### Single X2 Hub Limit

Similarly, only one `sofabatonHub` (X2) is tracked via `_hub_dev_id`. The
MQTT topics are keyed to `self.hubMac` (a single MAC), so multiple X2 hubs
would require multiple plugin instances or a refactor.

### Activity ID Collision Risk

Activities from X2 and X1 hubs share the same `_activities` dict keyed by
numeric activity ID. If both hubs use the same numeric ID for different
activities (which is possible since IDs are hub-local), the later-arriving
hub's activity will overwrite the earlier one. The `_hub_dev_id` tag on each
entry does not prevent the dict key collision.

### Race Condition: Activity Dict During Sync

`_sync_activity_devices()` iterates `self._activities` to create/update Indigo
devices. It does not hold `_activities_lock` during Indigo device creation
(which can be slow). If the X1 callback fires during this window, the lock
is briefly released between the remove and re-add steps, but the outer sync
runs without the lock. No crash has been observed but this is a latent issue.

### `sendKeyToCurrentActivity` — MQTT Only

This action finds the currently active activity and sends a key press via
MQTT. It does not check whether the active activity belongs to an X1 hub, and
X1 hubs have no equivalent "send key" command. If the active activity is an
X1 activity, the command silently fails (MQTT not connected or MAC mismatch).

### `stopAllActivities` — MQTT Only

The stop-all action publishes `activity_id=255` via MQTT. There is no X1
equivalent. X1 activities can only be stopped one at a time via
`deactivate(activity_id)`.

### `refreshActivities` Action — MQTT Only

The `refreshActivities` action only requests the MQTT activity list. X1
activity refresh requires calling `_x1_transport.request_activities()`
directly; the `RequestStatus` device action does this but the standalone
action does not.

---

## Dependency / Packaging Concerns

### `requirements.txt` Silent-Skip Risk

Indigo auto-installs from `requirements.txt` but may silently skip packages
if the interpreter architecture does not match the server (known issue
documented in workspace memory). If paho-mqtt fails to install, the plugin
logs an error and returns early from `startup()`, leaving the plugin
partially functional (no MQTT, but X1 may still work if the import succeeds).

### `zeroconf` Version Pinning

`zeroconf==0.148.0` is pinned. The zeroconf library has a history of
breaking changes between minor versions. `ifaddr` (a zeroconf dependency) is
not explicitly listed in `requirements.txt`, relying on pip to pull it in
transitively.

---

## Minor Issues

### Dedup Hash Collision

`_recent_messages` uses Python's `hash()` on the payload string for dedup.
`hash()` is not guaranteed to be collision-free and in CPython 3.3+ uses
random seeds, making identical runs produce different hashes. A SHA-256 or
MD5 hash would be more robust but is overkill for the 5-second dedup window.

### `discoverHub()` Blocks for 3 Seconds

The mDNS browse sleep is `time.sleep(3)` on the Indigo main thread (menu
callbacks run on the main thread). This stalls Indigo UI for 3 seconds on
every discovery run. Moving this to a background thread would be cleaner.

### No CI Test Runner

The version-check and release workflows do not run `pytest`. Tests pass
locally but there is no automated regression guard on PRs.

### `PluginConfig.xml` x1ListenPort vs Device listenPort

The plugin config UI has an `x1ListenPort` field but `_start_x1_transport`
reads `listenPort` from the *device* props, not the plugin prefs. The plugin
config field is effectively unused for actual transport configuration — it's
likely a legacy or planning artefact.
