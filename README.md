# Sofabaton Plugin for Indigo

Indigo plugin for the [Sofabaton X2](https://www.sofabaton.com/) universal remote hub. Control and monitor your Sofabaton activities via MQTT.

## Requirements

- **Indigo 2023.2+** (Python 3.10+)
- **Sofabaton X2 hub** with MQTT configured (via Sofabaton app)
- **MQTT broker** on your network (e.g. Mosquitto, or the Indigo MQTT Broker plugin)

## Installation

1. Download `Sofabaton.indigoPlugin` from the [latest release](https://github.com/simons-plugins/indigo-sofabaton/releases)
2. Double-click to install in Indigo
3. Python dependencies (`paho-mqtt`, `zeroconf`) are installed automatically on first load

## Setup

### 1. Configure your MQTT broker

The Sofabaton X2 hub connects to an external MQTT broker. Set this up in the Sofabaton app:

1. Open the Sofabaton app
2. Go to **Add Device** → **Home Assistant**
3. Enter your MQTT broker's IP address, port, and credentials

### 2. Configure the plugin

In Indigo, go to **Plugins → Sofabaton → Configure**:

- **Broker Host** — IP address of your MQTT broker
- **Broker Port** — Default `1883`
- **Username / Password** — If your broker requires authentication

### 3. Discover your hub

Go to **Plugins → Sofabaton → Discover Hub (mDNS)**

The plugin will find your Sofabaton hub on the network, save the MAC address, connect to MQTT, and auto-discover all activities.

## How It Works

### Devices

The plugin creates two types of Indigo devices:

| Device | Type | Description |
|--------|------|-------------|
| **Sofabaton Hub** | Custom | Shows the currently active activity name. Acts as the master status device. |
| **Sofabaton Activity** | Relay (on/off) | One per activity. Turn on to activate, turn off to deactivate. Auto-created on discovery. |

The hub device displays the current activity name directly in the Indigo device list — "Off" when nothing is active, or the activity name (e.g. "Watch TV").

### Listening

The plugin subscribes to MQTT topics from the hub. When someone uses the physical Sofabaton remote to switch activities, Indigo updates automatically in real time:

- Activity relay devices flip on/off
- Hub device shows the new activity name
- Triggers can fire on activity changes

### Controlling

You can control the Sofabaton from Indigo:

- **Turn on/off** activity devices to activate/deactivate activities
- **Send key presses** (volume, navigation, play/pause, etc.) to a specific activity or the current activity
- **Send macro and favorite keys** by ID
- **Stop all activities** with one action

## Actions

| Action | Target | Description |
|--------|--------|-------------|
| Turn On / Turn Off | Activity device | Activate or deactivate a specific activity |
| Send Key Press | Activity device | Send a remote key to a specific activity |
| Send Key to Current Activity | Any | Send a remote key to whatever activity is currently active |
| Send Macro Key | Activity device | Trigger a macro by key ID |
| Send Favorite Key | Activity device | Trigger a favorite by key ID + device ID |
| Refresh Activities | Plugin | Re-query the hub for activities |
| Stop All Activities | Plugin | Turn off all active activities |

### Available Keys

Up, Down, Left, Right, OK, Back, Home, Menu, Volume Up, Volume Down, Channel Up, Channel Down, Mute, Guide, Rewind, Play, Fast Forward, DVR, Pause, Exit, Red, Green, Yellow, Blue, A, B, C

## Menu Items

| Menu Item | Description |
|-----------|-------------|
| Discover Hub (mDNS) | Find Sofabaton hubs on the network and auto-configure |
| Refresh Activities | Re-query the hub for current activities |
| List Macro Keys | Log all macro keys for all activities to the Event Log |
| List Favorite Keys | Log all favorite keys for all activities to the Event Log |
| Dump Hub Config to Log | Write full hub configuration to the Event Log |

## MQTT Topics

The plugin communicates with the hub via these MQTT topics (where `{MAC}` is the hub's 12-character hex MAC address):

**Subscribe (from hub):**
- `activity/{MAC}/list` — Activity list
- `activity/{MAC}/activity_control_up` — Activity state changes
- `activity/{MAC}/keys_list` — Assigned keys
- `activity/{MAC}/macro_keys_list` — Macro keys
- `activity/{MAC}/favorites_keys_list` — Favorite keys

**Publish (to hub):**
- `activity/{MAC}/activity_control_down` — Activate/deactivate activities
- `activity/{MAC}/keys_control` — Send key presses
- `activity/{MAC}/macro_keys_control` — Send macro keys
- `activity/{MAC}/favorites_keys_control` — Send favorite keys

## Troubleshooting

### Hub not found via mDNS
- Ensure the Sofabaton hub and Indigo server are on the same network/VLAN
- The hub advertises as `_sofabaton_hub._udp.local.`

### MQTT not connecting
- Verify the broker is running and accessible from the Indigo server
- Check broker credentials match what's configured in the Sofabaton app
- Check the Indigo Event Log for connection errors

### Activities not appearing
- Ensure the hub is configured for MQTT in the Sofabaton app (Add Device → Home Assistant)
- Try **Plugins → Sofabaton → Refresh Activities**

## License

MIT
