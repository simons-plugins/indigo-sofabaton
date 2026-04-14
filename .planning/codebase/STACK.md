# STACK.md — Technology Stack

## Runtime

- **Python 3.10+** (Indigo 2023+ ships Python 3.10 via
  `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`)
- **macOS** only — runs inside Indigo's server process on the host Mac

## Indigo SDK

- **ServerApiVersion**: `3.0` (set in `Info.plist`)
- **IwsApiVersion**: `1.0.0`
- Plugin class inherits `indigo.PluginBase`
- All Indigo API calls go through the `indigo` module injected at runtime
- Device state updates use `dev.updateStateOnServer()` /
  `dev.updateStatesOnServer()`
- Device creation uses `indigo.device.create()`
- Device iteration uses `indigo.devices.iter("self.<typeId>")`

## Bundled Python Libraries

Located in `Sofabaton.indigoPlugin/Contents/Server Plugin/` (listed in
`requirements.txt`; Indigo auto-installs on plugin load):

| Library | Version | Purpose |
|---------|---------|---------|
| `paho-mqtt` | 2.1.0 | MQTT client for X2 hub communication |
| `zeroconf` | 0.148.0 | mDNS discovery for both hub types |
| `ifaddr` | 0.2.0 | Network interface enumeration (zeroconf dep) |

## Standard Library Modules Used

| Module | Purpose |
|--------|---------|
| `json` | MQTT JSON payload encode/decode |
| `time` | Hub pacing delays, dedup cache expiry |
| `threading` | MQTT loop, X1 TCP receive/callme threads, locks |
| `socket` | TCP server and UDP client sockets (X1 transport) |
| `select` | Non-blocking TCP receive with timeout |
| `struct` | Binary frame packing (X1 payload fields) |
| `random` | Jitter on CALL_ME retry interval |

## MQTT Client Usage

`paho-mqtt` 2.1 is used in **background loop mode** (`loop_start()` /
`loop_stop()`). The plugin uses the v2 callback API
(`CallbackAPIVersion.VERSION2`) with a fallback for older paho builds that
lack `CallbackAPIVersion`. Auto-reconnect is enabled via
`reconnect_delay_set(min=1, max=60)`.

## mDNS / zeroconf

`ServiceBrowser` is used for one-shot discovery on menu trigger. Two service
types are browsed: `_sofabaton_hub._udp.local.` (X2) and
`_x1hub._udp.local.` (X1/X1S). The `HVER` mDNS property distinguishes hub
model (1=X1, 2=X1S, 3=X2).

## Test Stack

- **pytest** (no version pinned in repo)
- `unittest.mock` — `Mock`, `MagicMock`, `patch`, `PropertyMock`
- `indigo` module is replaced wholesale with a `MagicMock` in `conftest.py`
  before any plugin import, so tests run without Indigo present
- Tests are in `tests/` at repo root; `conftest.py` adds the Server Plugin
  directory to `sys.path`

## Version / Release

- Version format: `YYYY.R.P` (e.g. `2026.1.0`)
- Version stored in `Sofabaton.indigoPlugin/Contents/Info.plist` as
  `PluginVersion`
- CI enforces a version bump per PR (`version-check.yml`)
- On merge to main, `create-release.yml` auto-creates a tagged GitHub release
  with a zipped `.indigoPlugin` bundle
