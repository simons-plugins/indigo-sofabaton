# CONVENTIONS.md — Python Style and Logging

## Python Style

### General

- Python 3.10+ syntax throughout
- `super().__init__(...)` — no explicit class args, Python 3 style
- f-strings are **not** used; the codebase uses `%` formatting consistently:
  ```python
  self.logger.info("Activity '%s' changed to %s" % (name, state))
  ```
- Type hints are absent — the codebase predates a type annotation policy
- Docstrings present on all public methods and module-level descriptions;
  single-line for simple getters, multi-line for complex behaviour

### Naming

- **Classes**: `PascalCase` (`Plugin`, `TcpTransport`)
- **Methods**: `camelCase` for Indigo callbacks (`deviceStartComm`,
  `actionControlDevice`, `sendKeyPress`), `snake_case` for internal helpers
  (`_start_mqtt`, `_fetch_catalogs`, `_update_hub_connection`)
- **Instance vars**: `camelCase` for prefs-backed attributes (`brokerHost`,
  `hubMac`, `logMqtt`), `_snake_case` with leading underscore for private
  state (`_mqtt`, `_activities`, `_x1_transport`)
- **Constants**: `UPPER_SNAKE_CASE` (`PUBLISH_DELAY`, `KEY_IDS`,
  `SYNC0`, `OP_CALL_ME`)
- **Module-level constants**: defined at top of each module before any class

### Private vs Public

Single underscore prefix (`_`) for methods and attributes not intended for
use outside the class. No double-underscore name-mangling. `TcpTransport`
public interface: `connect`, `disconnect`, `is_connected`, `send_frame`,
`request_activities`, `request_devices`, `request_commands`, `activate`,
`deactivate`, `send_command`, plus read-only properties `devices`,
`activities`, `commands`.

### Exception Handling

- Broad `except Exception as exc` used in plugin callbacks and transport
  loops — Indigo plugins must not propagate unhandled exceptions to the host
- `self.logger.exception(exc)` used when debug mode is on to log full
  traceback
- Specific `except (OSError, socket.error)` used in networking code
- `except (TypeError, AttributeError)` used in the paho callback API version
  detection fallback

### Import Style

- Standard library imports first, then third-party (`indigo`, `paho`), then
  local modules (`from protocol_const import ...`)
- Local imports inside `transport_tcp.py`, `frame_codec.py`,
  `opcode_handlers.py` use bare module names (not package paths) because
  they are co-located in the same directory and Indigo adds the Server Plugin
  directory to `sys.path`
- `TcpTransport` and `zeroconf` are imported inside method bodies in
  `plugin.py` to defer `ImportError` to runtime with a graceful log message
  rather than failing at startup

### Guard Patterns

```python
if not PAHO_AVAILABLE:
    self.logger.error("paho-mqtt library not found...")
    return
```

`PAHO_AVAILABLE` is set at module load time with a try/except around the
paho import.

---

## Logging

All logging goes through `self.logger` (the Indigo plugin logger). No direct
`print()` calls anywhere in production code.

### Log Levels Used

| Level | When |
|-------|------|
| `debug` | MQTT message content (gated on `logMqtt`), frame parse details, socket close errors, dedup skips |
| `info` | Connection events, activity state changes, device creation, catalog counts |
| `warning` | Unexpected MQTT disconnect, unconfigured MAC, CALL_ME send errors |
| `error` | Failed publishes, failed device creation, missing library, send failures |
| `exception` | Full tracebacks — only when `self.debug` is True |

### MQTT Logging Gate

```python
if self.logMqtt:
    self.logger.debug("MQTT << %s: %s" % (topic, payload_str))
```

Both inbound and outbound MQTT messages are logged at debug level, but only
when the `logMqtt` preference is enabled (itself only visible in the UI when
`showDebugInfo` is also enabled).

### X1 TCP Logging

Frame-level detail (individual opcodes, device/activity names from catalog
rows) logged at `debug`. Connection lifecycle events at `info`. Errors
(send failure, receive error, bind failure) at `error`.

---

## Indigo Callback Conventions

Indigo expects specific method signatures for callbacks:

```python
def actionControlDevice(self, action, dev): ...
def deviceStartComm(self, dev): ...
def deviceStopComm(self, dev): ...
def sendKeyPress(self, action, dev): ...          # action with device filter
def sendKeyToCurrentActivity(self, action): ...   # action without device
def discoverHub(self): ...                        # menu item
def getX1ActivityList(self, filter="", valuesDict=None, typeId="", targetId=0): ...
```

All Indigo callbacks call `super()` where the SDK requires it
(`deviceStartComm`, `deviceStopComm`). `stateListOrDisplayStateIdChanged()`
is called in `deviceStartComm` to force Indigo to refresh the state display.

---

## Thread Usage Pattern

Threads created with `threading.Thread(..., daemon=True)`. Daemon flag ensures
threads are killed when the plugin process exits without needing explicit join
in the happy path. The `disconnect()` method joins threads with a 5-second
timeout for clean shutdown.

`threading.Timer` is used for scheduled one-shot operations (reconnect delay,
post-connect activity request delay) rather than sleeping in a thread.
