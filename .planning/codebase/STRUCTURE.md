# STRUCTURE.md — Directory Layout

## Repository Root

```
indigo-sofabatton-plugin/
├── .github/
│   └── workflows/
│       ├── create-release.yml    # Auto-creates tagged release + zip on merge to main
│       └── version-check.yml     # CI: blocks PR if PluginVersion not bumped
├── .planning/
│   └── codebase/                 # This documentation
├── docs/
│   └── plans/
│       ├── 2026-03-18-x1-implementation-plan.md
│       └── 2026-03-18-x1-support-design.md   # Design doc for X1/X1S TCP support
├── tests/
│   ├── conftest.py               # Shared fixtures, indigo mock, Plugin factory
│   ├── test_actions.py           # Custom action callbacks (sendKeyPress etc.)
│   ├── test_frame_codec.py       # Binary frame build/parse/extract
│   ├── test_message_handling.py  # MQTT message dispatch handlers
│   ├── test_opcode_handlers.py   # opcode_handlers.py: parse_device/activity rows
│   ├── test_protocol_const.py    # Protocol constants sanity checks
│   ├── test_publishing.py        # MQTT publish helpers
│   ├── test_transport_tcp.py     # TcpTransport unit tests
│   ├── test_validation.py        # Input validation paths
│   └── test_x1_integration.py   # X1/X1S integration scenarios
├── CLAUDE.md                     # Project-specific Claude instructions
└── README.md                     # User-facing documentation
```

## Plugin Bundle

```
Sofabaton.indigoPlugin/
└── Contents/
    ├── Info.plist                # Bundle metadata, PluginVersion, CFBundleIdentifier
    └── Server Plugin/
        ├── plugin.py             # Main Plugin class (MQTT + X1 orchestration)
        ├── transport_tcp.py      # TcpTransport: X1/X1S connection lifecycle
        ├── frame_codec.py        # Binary frame build / parse / extract
        ├── opcode_handlers.py    # Frame payload parsers, dispatch_opcode()
        ├── protocol_const.py     # Opcodes, sync bytes, ports, timing constants
        ├── requirements.txt      # paho-mqtt, zeroconf (Indigo auto-installs)
        ├── Actions.xml           # Action definitions
        ├── Devices.xml           # Device type definitions
        ├── MenuItems.xml         # Plugin menu items
        └── PluginConfig.xml      # Plugin preferences UI
```

---

## Key File Details

### `plugin.py`

~960 lines. The entire plugin logic lives here. Sections:

1. Imports and `KEY_IDS` constant dict (27 keys)
2. `Plugin.__init__()` — prefs, MQTT config, all instance vars
3. Plugin lifecycle (`startup`, `shutdown`, `deviceStartComm`, `deviceStopComm`)
4. MQTT connection management (`_start_mqtt`, `_stop_mqtt`, callbacks)
5. MQTT message handling (`_on_message`, `_handle_activity_list`, etc.)
6. Indigo device sync (`_create_hub_device`, `_sync_activity_devices`,
   state update helpers)
7. MQTT publish helpers (`_publish`, `_request_activity_list`, etc.)
8. X1/X1S transport management (`_start_x1_transport`, `_stop_x1_transport`,
   callbacks, `_get_transport_for_activity`, `_send_activity_command`)
9. `runConcurrentThread` (dedup cache pruning)
10. `actionControlDevice` (Turn On/Off/Toggle/RequestStatus)
11. Custom action callbacks (`sendKeyPress`, `sendMacroKey`, `sendFavoriteKey`,
    `sendKeyToCurrentActivity`, `refreshActivities`, `stopAllActivities`,
    `sendDeviceCommand`)
12. Dynamic list callbacks for action UI (`getX1ActivityList`,
    `getX1DeviceList`, `getX1CommandList`)
13. Menu callbacks (`discoverHub`, `_create_discovered_hub`,
    `refreshActivitiesMenu`, `listMacroKeys`, `listFavoriteKeys`,
    `listX1Devices`, `listX1Commands`, `dumpConfig`)
14. Plugin config UI callbacks (`getDeviceFolderList`, `closedPrefsConfigUi`)

### `transport_tcp.py`

~410 lines. `TcpTransport` class only. No Indigo imports.

### `frame_codec.py`

~136 lines. Pure functions: `build_frame`, `build_callme_packet`,
`parse_frame`, `extract_frames`, `_find_sync`. No Indigo imports.

### `opcode_handlers.py`

~112 lines. Pure functions: `parse_device_catalog_row`,
`parse_activity_catalog_row`, `parse_button_record`, `dispatch_opcode`,
`_decode_label`. No Indigo imports.

### `protocol_const.py`

~63 lines. Constants only: sync bytes, opcodes, ports, timing, hub version
strings, mDNS service types.

---

## Devices.xml — Device Types

| `id` | `type` | `allowUserCreation` | UI States |
|------|--------|---------------------|-----------|
| `sofabatonHub` | `custom` | `true` | connectionStatus, activeActivity, activeActivityId |
| `sofabatonX1Hub` | `custom` | `false` | connectionStatus, activeActivity, activeActivityId, hubModel, deviceCount |
| `sofabatonActivity` | `relay` | `false` | onOffState (bool) |

`sofabatonHub` exposes a MAC address text field in its config UI.
`sofabatonX1Hub` exposes hubIp, listenPort, and hidden fields for macAddress
and hubModel (populated by discovery). `sofabatonActivity` has three hidden
props (hubDevice, activityId, activityName).

---

## Actions.xml — Actions

| `id` | `deviceFilter` | Callback |
|------|---------------|---------|
| `sendKeyPress` | `self.sofabatonActivity` | `sendKeyPress` |
| `sendMacroKey` | `self.sofabatonActivity` | `sendMacroKey` |
| `sendFavoriteKey` | `self.sofabatonActivity` | `sendFavoriteKey` |
| `sendKeyToCurrentActivity` | (none) | `sendKeyToCurrentActivity` |
| `refreshActivities` | (none) | `refreshActivities` |
| `stopAllActivities` | (none) | `stopAllActivities` |
| `sendDeviceCommand` | (none) | `sendDeviceCommand` |

`sendDeviceCommand` uses three dynamic-list fields backed by
`getX1ActivityList`, `getX1DeviceList`, `getX1CommandList`.

---

## MenuItems.xml — Menu Items

| `id` | Label | Callback |
|------|-------|---------|
| `discoverHub` | Discover Hubs (mDNS) | `discoverHub` |
| `refreshActivities` | Refresh Activities | `refreshActivitiesMenu` |
| `listMacroKeys` | List Macro Keys (Event Log) | `listMacroKeys` |
| `listFavoriteKeys` | List Favorite Keys (Event Log) | `listFavoriteKeys` |
| `listX1Devices` | List X1 Devices (Event Log) | `listX1Devices` |
| `listX1Commands` | List X1 Commands (Event Log) | `listX1Commands` |
| `dumpConfig` | Dump Hub Config to Log | `dumpConfig` |

---

## PluginConfig.xml — Plugin Preferences

Sections: MQTT broker settings (host, port, username, password), Hub MAC
address, X1/X1S listen port base, device folder menu, auto-discover checkbox,
debug/logMqtt checkboxes. `logMqtt` is only visible when `showDebugInfo=true`.
