# CLAUDE.md

## Release Process

- **Bump `PluginVersion`** in `Sofabaton.indigoPlugin/Contents/Info.plist` with every PR — CI enforces this
- Version format: `YYYY.R.P` (year.release.patch), e.g. `2026.0.2`
- A version-check workflow blocks PRs that reuse an existing tag
- On merge to main, the create-release workflow auto-creates a tagged GitHub release with the `.indigoPlugin.zip` bundle

## Plugin Overview

**Sofabaton** - Indigo plugin for Sofabaton X2 universal remote hub

- **Version**: 0.1.0
- **Bundle ID**: `com.simons-plugins.sofabaton`
- **Protocol**: MQTT (via paho-mqtt 2.1)
- **Hub Model**: Sofabaton X2 (native MQTT support)

Controls and monitors a Sofabaton X2 hub via MQTT. The hub must be configured (via Sofabaton app) to connect to the same MQTT broker.

## Architecture

### Communication

- **Transport**: MQTT via paho-mqtt library (bundled in Packages/)
- **Discovery**: mDNS `_sofabaton_hub._udp.local.` via zeroconf (bundled)
- **Topics**: `activity/{MAC}/*` and `device/{MAC}/*` where MAC is 12-char uppercase hex
- **Payloads**: JSON
- **Hub constraint**: Single-threaded processing, 200ms delay between publishes

### Device Types

| Type ID | Indigo Type | Description |
|---------|-------------|-------------|
| `sofabatonHub` | custom | The hub itself — shows connection status and active activity |
| `sofabatonActivity` | relay | One per activity — on/off maps to activity active/inactive |

Activity devices are auto-created when the plugin discovers activities from the hub.

### MQTT Topics Used

**Subscribe (receive from hub):**
- `activity/{mac}/list` — Activity list response
- `activity/{mac}/activity_control_up` — Activity state changes (from remote/app)
- `activity/{mac}/keys_list` — Assigned key list
- `activity/{mac}/macro_keys_list` — Macro key list
- `activity/{mac}/favorites_keys_list` — Favorite key list
- `device/{mac}/list` — Device list response
- `device/{mac}/keys_list` — Device key list

**Publish (send to hub):**
- `activity/{mac}/list_request` — Request activity list
- `activity/{mac}/activity_control_down` — Activate/deactivate activity
- `activity/{mac}/keys_control` — Send key press
- `activity/{mac}/macro_keys_control` — Send macro key
- `activity/{mac}/favorites_keys_control` — Send favorite key

### Key IDs (27 hardware remote keys)

| Key | ID | Key | ID | Key | ID |
|-----|----|-----|----|-----|----|
| up | 174 | volume_up | 182 | rewind | 187 |
| down | 178 | volume_down | 185 | play | 156 |
| left | 175 | mute | 184 | fast_forward | 189 |
| right | 177 | channel_up | 183 | pause | 188 |
| ok | 176 | channel_down | 186 | dvr | 155 |
| back | 179 | guide | 157 | exit | 154 |
| home | 180 | red | 190 | a | 153 |
| menu | 181 | green | 191 | b | 152 |
| | | yellow | 192 | c | 151 |
| | | blue | 193 | | |

### Firmware Quirk

Favorite key control uses `device_id` in the `activity_id` field (not the actual activity_id). This is a known Sofabaton firmware design issue.

## Prerequisites

1. **MQTT Broker** — Mosquitto, or Indigo's MQTT Broker plugin by FlyingDiver
2. **Sofabaton X2 hub** configured to connect to your MQTT broker (via Sofabaton app → Add Device → Home Assistant)

## Available Actions

| Action | Description |
|--------|-------------|
| Turn On/Off activity | Activate or deactivate a Sofabaton activity |
| Send Key Press | Send any of the 27 remote keys to an activity |
| Send Macro Key | Trigger a macro by key ID |
| Send Favorite Key | Trigger a favorite by key ID + device ID |
| Refresh Activities | Re-query hub for activity list |
| Stop All Activities | Turn off all active activities |

## Menu Items

| Menu Item | Description |
|-----------|-------------|
| Discover Hub (mDNS) | Find Sofabaton hubs on the network |
| Refresh Activities | Query hub for current activities |
| List Macro Keys | Log all macro keys for all activities |
| List Favorite Keys | Log all favorite keys for all activities |

## Testing

```bash
# Copy to Indigo server
cp -r "Sofabaton.indigoPlugin" "/Volumes/Macintosh HD-1/Library/Application Support/Perceptive Automation/Indigo 2025.1/Plugins/"
```

Enable via Indigo: Plugins → Manage Plugins → Enable Sofabaton

## Dependencies (bundled)

- `paho-mqtt` 2.1.0 — MQTT client
- `zeroconf` 0.148.0 — mDNS discovery
- `ifaddr` 0.2.0 — Network interface addresses (zeroconf dependency)
