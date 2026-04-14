# TESTING.md — Test Approach

## Overview

Tests live in `tests/` at repo root and run with `pytest`. There is no CI
test step currently — tests are run manually by the developer. The test suite
covers all pure-Python modules and the plugin class independently of Indigo.

## Running Tests

```bash
cd /path/to/indigo-sofabatton-plugin
pytest tests/ -v
```

No special env vars or fixtures files are required beyond what conftest.py
provides.

## Indigo Isolation Strategy

Indigo is not available outside the Indigo server process. Tests replace the
`indigo` module wholesale with a `MagicMock` before any plugin import:

```python
indigo_mock = MagicMock()
indigo_mock.PluginBase = object           # Plugin inherits object in tests
indigo_mock.kProtocol.Plugin = "Plugin"
indigo_mock.kDeviceAction.TurnOn = 1
# ... etc.
sys.modules["indigo"] = indigo_mock
```

This is done once at module scope in `conftest.py`, so it applies to all
test files that `import conftest` (all of them, by pytest convention).

The `Plugin` instance in fixtures is created by bypassing `__init__` via
`Plugin.__new__(Plugin)` and manually setting all instance attributes,
mirroring what `__init__` would do. This avoids MQTT connection attempts and
Indigo device iteration during test setup.

## Test Files

| File | What it tests |
|------|--------------|
| `test_protocol_const.py` | Constant values (sync bytes, port numbers, version map) |
| `test_frame_codec.py` | `build_frame`, `build_callme_packet`, `parse_frame`, `extract_frames` |
| `test_opcode_handlers.py` | `parse_device_catalog_row`, `parse_activity_catalog_row`, `dispatch_opcode` |
| `test_transport_tcp.py` | `TcpTransport` init, callbacks, send methods (sockets mocked) |
| `test_message_handling.py` | `_on_message`, `_handle_activity_list`, `_handle_activity_state` |
| `test_publishing.py` | `_publish`, `_send_activity_control`, `_send_key_control`, etc. |
| `test_actions.py` | `actionControlDevice`, `sendKeyPress`, `sendMacroKey`, `sendFavoriteKey` |
| `test_validation.py` | Input validation paths (bad IDs, missing config, etc.) |
| `test_x1_integration.py` | Full X1/X1S scenarios: connect, catalog sync, activate, deactivate |

## Key Fixtures (`conftest.py`)

| Fixture | Provides |
|---------|---------|
| `mock_logger` | `Mock()` with debug/info/warning/error/exception attributes |
| `default_prefs` | Dict of typical plugin preferences |
| `plugin` | `Plugin` instance with all attrs set, `_mqtt` mocked, logger injected |
| `hub_device` | `MockIndigoDevice` for `sofabatonHub` with connected state |
| `activity_device` | `MockIndigoDevice` for `sofabatonActivity` (Watch TV) |
| `activity_list_payload` | Three-activity MQTT payload dict |
| `keys_list_payload` | Three-key MQTT payload |
| `macro_keys_payload` | Two macro key payload |
| `favorites_keys_payload` | Two favorite key payload |

`MockIndigoDevice` is a handwritten stub that tracks `states`, `onState`,
`_state_image`, `_error_state`, and `_plugin_props`. It implements all state
update methods used by the plugin.

## Coverage Focus

The test suite is strongest on the pure protocol logic:

- **Frame codec**: all build/parse/extract edge cases including corrupt sync,
  bad checksum, incomplete frame, leading garbage, mixed valid+corrupt frames
- **Opcode dispatch**: X1 vs X1S encoding differences (UTF-8 vs UTF-16BE,
  active flag position)
- **Activity state machine**: only-one-active enforcement, activity_id=255
  stop-all, unknown activity auto-refresh

Areas with lighter coverage:
- mDNS discovery (`discoverHub`) — requires live zeroconf mock
- MQTT reconnect edge cases
- TCP reconnect loop timing

## Testing Against Live Hardware

No automated live tests. Manual process:

1. Copy updated files to Indigo server:
   ```bash
   cp -r "Sofabaton.indigoPlugin" \
     "/Volumes/Macintosh HD-1/Library/Application Support/Perceptive Automation/Indigo 2025.1/Plugins/"
   ```
2. Reload via MCP: `mcp__indigo__restart_plugin(plugin_id="com.simons-plugins.sofabaton")`
3. Check event log: `mcp__indigo__query_event_log()`
4. Trigger menu items (Discover Hub, Refresh Activities) to verify end-to-end
