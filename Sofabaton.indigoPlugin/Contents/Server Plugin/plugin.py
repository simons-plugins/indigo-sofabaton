#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Sofabaton X2 Hub - Indigo Plugin
# Controls Sofabaton X2 universal remote hub via MQTT
####################

import json
import time
import threading

import indigo

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

# Hardware remote key ID map (27 keys)
KEY_IDS = {
    "up": 174, "down": 178, "left": 175, "right": 177, "ok": 176,
    "back": 179, "home": 180, "menu": 181,
    "volume_up": 182, "volume_down": 185, "mute": 184,
    "channel_up": 183, "channel_down": 186, "guide": 157,
    "rewind": 187, "play": 156, "fast_forward": 189,
    "dvr": 155, "pause": 188, "exit": 154,
    "red": 190, "green": 191, "yellow": 192, "blue": 193,
    "a": 153, "b": 152, "c": 151,
}

PUBLISH_DELAY = 0.2  # Hub is single-threaded; space out requests


class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs, **kwargs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs, **kwargs)

        self.debug = pluginPrefs.get("showDebugInfo", False)
        self.logMqtt = pluginPrefs.get("logMqtt", False)

        # MQTT config
        self.brokerHost = pluginPrefs.get("mqttBrokerHost", "localhost")
        self.brokerPort = int(pluginPrefs.get("mqttBrokerPort", 1883))
        self.mqttUsername = pluginPrefs.get("mqttUsername", "")
        self.mqttPassword = pluginPrefs.get("mqttPassword", "")
        self.hubMac = pluginPrefs.get("hubMac", "").upper().replace(":", "").replace("-", "")
        self.autoDiscover = pluginPrefs.get("autoDiscover", True)

        # MQTT client
        self._mqtt = None
        self._mqtt_connected = False
        self._mqtt_lock = threading.Lock()
        self._publish_lock = threading.Lock()

        # Activity tracking
        self._activities = {}  # activity_id -> {"name": str, "state": str}
        self._pending_requests = {}  # topic -> callback

        # Dedup cache: prevent processing duplicate messages
        self._recent_messages = {}  # topic -> (payload_hash, timestamp)
        self.DEDUP_SECONDS = 5

        # Hub device reference
        self._hub_dev_id = None

    # -------------------------------------------------------------------------
    # Plugin lifecycle
    # -------------------------------------------------------------------------

    def startup(self):
        self.logger.info("Sofabaton plugin starting")

        if not PAHO_AVAILABLE:
            self.logger.error(
                "paho-mqtt library not found. Install it in the plugin's "
                "Packages directory or via pip for the Indigo Python."
            )
            return

        # Find existing hub device
        for dev in indigo.devices.iter("self.sofabatonHub"):
            self._hub_dev_id = dev.id
            break

        self._start_mqtt()

    def shutdown(self):
        self.logger.info("Sofabaton plugin stopping")
        self._stop_mqtt()

    def deviceStartComm(self, dev):
        super().deviceStartComm(dev)
        dev.stateListOrDisplayStateIdChanged()

        if dev.deviceTypeId == "sofabatonHub":
            self._hub_dev_id = dev.id
            mac = dev.pluginProps.get("macAddress", "").upper().replace(":", "").replace("-", "")
            if mac and mac != self.hubMac:
                self.hubMac = mac
                self.logger.info("Hub MAC set from device: %s" % self.hubMac)
                # Reconnect with new MAC to re-subscribe
                if self._mqtt_connected:
                    self._stop_mqtt()
                    self._start_mqtt()

    def deviceStopComm(self, dev):
        super().deviceStopComm(dev)

    # -------------------------------------------------------------------------
    # MQTT connection management
    # -------------------------------------------------------------------------

    def _start_mqtt(self):
        if not PAHO_AVAILABLE:
            return
        if not self.hubMac:
            self.logger.warning("Hub MAC address not configured - MQTT not started")
            return

        self.logger.info("Connecting to MQTT broker %s:%d" % (self.brokerHost, self.brokerPort))

        try:
            self._mqtt = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="indigo-sofabaton-%s" % self.hubMac[:8],
            )
        except (TypeError, AttributeError):
            # Older paho-mqtt without CallbackAPIVersion
            self._mqtt = mqtt.Client(client_id="indigo-sofabaton-%s" % self.hubMac[:8])

        if self.mqttUsername:
            self._mqtt.username_pw_set(self.mqttUsername, self.mqttPassword)

        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message = self._on_message

        self._mqtt.reconnect_delay_set(min_delay=1, max_delay=60)

        try:
            self._mqtt.connect_async(self.brokerHost, self.brokerPort, keepalive=60)
            self._mqtt.loop_start()
        except Exception as exc:
            self.logger.error("MQTT connect failed: %s" % exc)

    def _stop_mqtt(self):
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass
            self._mqtt = None
            self._mqtt_connected = False
        self._update_hub_connection("disconnected")

    def _on_connect(self, client, userdata, flags, rc, *args):
        if hasattr(rc, 'value'):
            rc_val = rc.value
        else:
            rc_val = rc

        if rc_val == 0:
            self.logger.info("Connected to MQTT broker")
            self._mqtt_connected = True
            self._update_hub_connection("connected")
            self._subscribe_all()

            if self.autoDiscover:
                # Slight delay to let subscriptions settle
                threading.Timer(1.0, self._request_activity_list).start()
        else:
            self.logger.error("MQTT connection failed with code %s" % rc)
            self._update_hub_connection("error")

    def _on_disconnect(self, client, userdata, rc, *args):
        self._mqtt_connected = False
        self._update_hub_connection("disconnected")
        if hasattr(rc, 'value'):
            rc_val = rc.value
        else:
            rc_val = rc
        if rc_val != 0:
            self.logger.warning("Unexpected MQTT disconnect (rc=%s), will auto-reconnect" % rc)
        else:
            self.logger.info("MQTT disconnected")

    def _subscribe_all(self):
        mac = self.hubMac
        topics = [
            "activity/%s/list" % mac,
            "activity/%s/activity_control_up" % mac,
            "activity/%s/keys_list" % mac,
            "activity/%s/macro_keys_list" % mac,
            "activity/%s/favorites_keys_list" % mac,
            "device/%s/list" % mac,
            "device/%s/keys_list" % mac,
        ]
        for topic in topics:
            self._mqtt.subscribe(topic)
            self.logger.debug("Subscribed to %s" % topic)

    # -------------------------------------------------------------------------
    # MQTT message handling
    # -------------------------------------------------------------------------

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode("utf-8")

            if self.logMqtt:
                self.logger.debug("MQTT << %s: %s" % (topic, payload_str))

            # Dedup check
            payload_hash = hash(payload_str)
            now = time.time()
            if topic in self._recent_messages:
                prev_hash, prev_time = self._recent_messages[topic]
                if prev_hash == payload_hash and (now - prev_time) < self.DEDUP_SECONDS:
                    self.logger.debug("Duplicate message ignored on %s" % topic)
                    return
            self._recent_messages[topic] = (payload_hash, now)

            payload = json.loads(payload_str)
            mac = self.hubMac

            if topic == "activity/%s/list" % mac:
                self._handle_activity_list(payload)
            elif topic == "activity/%s/activity_control_up" % mac:
                self._handle_activity_state(payload)
            elif topic == "activity/%s/keys_list" % mac:
                self._handle_keys_list(payload, "assigned")
            elif topic == "activity/%s/macro_keys_list" % mac:
                self._handle_keys_list(payload, "macro")
            elif topic == "activity/%s/favorites_keys_list" % mac:
                self._handle_keys_list(payload, "favorite")
            elif topic == "device/%s/list" % mac:
                self._handle_device_list(payload)
            elif topic == "device/%s/keys_list" % mac:
                self._handle_keys_list(payload, "device")

        except Exception as exc:
            self.logger.error("Error processing MQTT message: %s" % exc)
            if self.debug:
                self.logger.exception(exc)

    def _handle_activity_list(self, payload):
        activities = payload.get("data", [])
        self.logger.info("Received %d activities from hub" % len(activities))

        self._activities = {}
        for act in activities:
            act_id = act.get("activity_id")
            act_name = act.get("activity_name", "Activity %d" % act_id)
            act_state = act.get("state", "off")
            self._activities[act_id] = {"name": act_name, "state": act_state}

        # Create or update Indigo devices for each activity
        self._sync_activity_devices()

    def _handle_activity_state(self, payload):
        act_id = payload.get("activity_id")
        state = payload.get("state", "off")

        if act_id == 255:
            # All activities stopped
            self.logger.info("All activities stopped")
            for aid in self._activities:
                self._activities[aid]["state"] = "off"
            self._update_all_activity_states()
            self._update_hub_active_activity(None)
            return

        if act_id in self._activities:
            old_state = self._activities[act_id]["state"]
            self._activities[act_id]["state"] = state
            name = self._activities[act_id]["name"]
            if old_state != state:
                self.logger.info("Activity '%s' changed to %s" % (name, state))

            # Only one activity can be on at a time
            if state == "on":
                for aid in self._activities:
                    if aid != act_id:
                        self._activities[aid]["state"] = "off"
                self._update_hub_active_activity(act_id)
            else:
                self._update_hub_active_activity(None)
        else:
            self.logger.debug("State update for unknown activity %s" % act_id)
            self._activities[act_id] = {"name": "Activity %d" % act_id, "state": state}

        self._update_all_activity_states()

    def _handle_keys_list(self, payload, key_type):
        act_id = payload.get("activity_id", payload.get("device_id", "?"))
        keys = payload.get("data", [])
        self.logger.info("Received %d %s keys for activity/device %s" % (len(keys), key_type, act_id))
        for key in keys:
            key_id = key.get("key_id")
            key_name = key.get("key_name", "")
            if key_name:
                self.logger.info("  %s key: id=%d, name='%s'" % (key_type, key_id, key_name))
            else:
                self.logger.info("  %s key: id=%d" % (key_type, key_id))

    def _handle_device_list(self, payload):
        devices = payload.get("data", [])
        self.logger.info("Received %d devices from hub" % len(devices))
        for dev_info in devices:
            dev_id = dev_info.get("device_id")
            dev_name = dev_info.get("device_name", "Device %d" % dev_id)
            self.logger.info("  Device: id=%d, name='%s'" % (dev_id, dev_name))

    # -------------------------------------------------------------------------
    # Indigo device synchronisation
    # -------------------------------------------------------------------------

    def _sync_activity_devices(self):
        existing = {}
        for dev in indigo.devices.iter("self.sofabatonActivity"):
            act_id = int(dev.pluginProps.get("activityId", 0))
            existing[act_id] = dev

        for act_id, act_info in self._activities.items():
            if act_id in existing:
                # Update name if changed
                dev = existing[act_id]
                stored_name = dev.pluginProps.get("activityName", "")
                if stored_name != act_info["name"]:
                    props = dev.pluginProps
                    props["activityName"] = act_info["name"]
                    dev.replacePluginPropsOnServer(props)
                is_on = act_info["state"] == "on"
                dev.updateStateOnServer("onOffState", is_on)
                if is_on:
                    dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                else:
                    dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
            else:
                # Create new activity device
                dev_name = "Sofabaton - %s" % act_info["name"]
                self.logger.info("Creating activity device: %s" % dev_name)
                props = {
                    "activityId": str(act_id),
                    "activityName": act_info["name"],
                    "hubDevice": str(self._hub_dev_id) if self._hub_dev_id else "",
                }
                try:
                    new_dev = indigo.device.create(
                        protocol=indigo.kProtocol.Plugin,
                        deviceTypeId="sofabatonActivity",
                        name=dev_name,
                        props=props,
                    )
                    is_on = act_info["state"] == "on"
                    new_dev.updateStateOnServer("onOffState", is_on)
                    if is_on:
                        new_dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                    else:
                        new_dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                except Exception as exc:
                    self.logger.error("Failed to create activity device: %s" % exc)

    def _update_all_activity_states(self):
        for dev in indigo.devices.iter("self.sofabatonActivity"):
            act_id = int(dev.pluginProps.get("activityId", 0))
            if act_id in self._activities:
                is_on = self._activities[act_id]["state"] == "on"
                if dev.onState != is_on:
                    dev.updateStateOnServer("onOffState", is_on)
                    if is_on:
                        dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                    else:
                        dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)

    def _update_hub_connection(self, status):
        if self._hub_dev_id:
            try:
                dev = indigo.devices[self._hub_dev_id]
                dev.updateStateOnServer("connectionStatus", status, uiValue=status.title())
                if status == "connected":
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                elif status == "error":
                    dev.setErrorStateOnServer("Connection Error")
                else:
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            except Exception:
                pass

    def _update_hub_active_activity(self, act_id):
        if self._hub_dev_id:
            try:
                dev = indigo.devices[self._hub_dev_id]
                if act_id and act_id in self._activities:
                    name = self._activities[act_id]["name"]
                    dev.updateStatesOnServer([
                        {"key": "activeActivity", "value": name},
                        {"key": "activeActivityId", "value": act_id},
                    ])
                else:
                    dev.updateStatesOnServer([
                        {"key": "activeActivity", "value": "None"},
                        {"key": "activeActivityId", "value": 0},
                    ])
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # MQTT publishing helpers
    # -------------------------------------------------------------------------

    def _publish(self, topic, payload):
        if not self._mqtt_connected:
            self.logger.error("Not connected to MQTT broker")
            return False

        with self._publish_lock:
            payload_str = json.dumps(payload)
            if self.logMqtt:
                self.logger.debug("MQTT >> %s: %s" % (topic, payload_str))
            try:
                result = self._mqtt.publish(topic, payload_str)
                result.wait_for_publish(timeout=5)
                time.sleep(PUBLISH_DELAY)  # Hub pacing
                return True
            except Exception as exc:
                self.logger.error("MQTT publish failed: %s" % exc)
                return False

    def _request_activity_list(self):
        topic = "activity/%s/list_request" % self.hubMac
        self._publish(topic, {"data": "activity_list"})

    def _send_activity_control(self, activity_id, state):
        topic = "activity/%s/activity_control_down" % self.hubMac
        return self._publish(topic, {"data": {"activity_id": activity_id, "state": state}})

    def _send_key_control(self, activity_id, key_id):
        topic = "activity/%s/keys_control" % self.hubMac
        return self._publish(topic, {"data": {"activity_id": activity_id, "key_id": key_id}})

    def _send_macro_key(self, activity_id, key_id):
        topic = "activity/%s/macro_keys_control" % self.hubMac
        return self._publish(topic, {"data": {"activity_id": activity_id, "key_id": key_id}})

    def _send_favorite_key(self, device_id, key_id):
        # Firmware quirk: activity_id field must contain device_id for favorites
        topic = "activity/%s/favorites_keys_control" % self.hubMac
        return self._publish(topic, {"data": {"activity_id": device_id, "key_id": key_id}})

    # -------------------------------------------------------------------------
    # Concurrent thread
    # -------------------------------------------------------------------------

    def runConcurrentThread(self):
        try:
            while True:
                # Clean old dedup entries
                now = time.time()
                expired = [k for k, (_, t) in self._recent_messages.items()
                           if now - t > self.DEDUP_SECONDS * 2]
                for k in expired:
                    del self._recent_messages[k]

                self.sleep(30)
        except self.StopThread:
            pass

    # -------------------------------------------------------------------------
    # Device control actions (Turn On / Turn Off activity)
    # -------------------------------------------------------------------------

    def actionControlDevice(self, action, dev):
        if dev.deviceTypeId != "sofabatonActivity":
            return

        act_id = int(dev.pluginProps.get("activityId", 0))
        act_name = dev.pluginProps.get("activityName", "Activity %d" % act_id)

        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            if self._send_activity_control(act_id, "on"):
                self.logger.info("Activated '%s'" % act_name)
                dev.updateStateOnServer("onOffState", True)
                dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                # Turn off other activities in Indigo
                for other_dev in indigo.devices.iter("self.sofabatonActivity"):
                    if other_dev.id != dev.id:
                        other_dev.updateStateOnServer("onOffState", False)
                        other_dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                self._update_hub_active_activity(act_id)
            else:
                self.logger.error("Failed to activate '%s'" % act_name)

        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            if self._send_activity_control(act_id, "off"):
                self.logger.info("Deactivated '%s'" % act_name)
                dev.updateStateOnServer("onOffState", False)
                dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                self._update_hub_active_activity(None)
            else:
                self.logger.error("Failed to deactivate '%s'" % act_name)

        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            new_state = not dev.onState
            if self._send_activity_control(act_id, "on" if new_state else "off"):
                self.logger.info("%s '%s'" % ("Activated" if new_state else "Deactivated", act_name))
                dev.updateStateOnServer("onOffState", new_state)
                dev.updateStateImageOnServer(
                    indigo.kStateImageSel.PowerOn if new_state else indigo.kStateImageSel.PowerOff
                )
                if new_state:
                    for other_dev in indigo.devices.iter("self.sofabatonActivity"):
                        if other_dev.id != dev.id:
                            other_dev.updateStateOnServer("onOffState", False)
                            other_dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                self._update_hub_active_activity(act_id if new_state else None)
            else:
                self.logger.error("Failed to toggle '%s'" % act_name)

        elif action.deviceAction == indigo.kDeviceAction.RequestStatus:
            self._request_activity_list()

    # -------------------------------------------------------------------------
    # Custom action callbacks
    # -------------------------------------------------------------------------

    def sendKeyPress(self, action, dev):
        act_id = int(dev.pluginProps.get("activityId", 0))
        key_name = action.props.get("keyName", "ok")
        key_id = KEY_IDS.get(key_name)
        if key_id is None:
            self.logger.error("Unknown key name: %s" % key_name)
            return
        act_name = dev.pluginProps.get("activityName", "Activity %d" % act_id)
        if self._send_key_control(act_id, key_id):
            self.logger.info("Sent '%s' key to '%s'" % (key_name, act_name))
        else:
            self.logger.error("Failed to send '%s' key to '%s'" % (key_name, act_name))

    def sendMacroKey(self, action, dev):
        act_id = int(dev.pluginProps.get("activityId", 0))
        try:
            key_id = int(action.props.get("macroKeyId", 0))
        except ValueError:
            self.logger.error("Invalid macro key ID")
            return
        act_name = dev.pluginProps.get("activityName", "Activity %d" % act_id)
        if self._send_macro_key(act_id, key_id):
            self.logger.info("Sent macro key %d to '%s'" % (key_id, act_name))
        else:
            self.logger.error("Failed to send macro key to '%s'" % act_name)

    def sendFavoriteKey(self, action, dev):
        try:
            key_id = int(action.props.get("favoriteKeyId", 0))
            device_id = int(action.props.get("favoriteDeviceId", 0))
        except ValueError:
            self.logger.error("Invalid favorite key or device ID")
            return
        act_name = dev.pluginProps.get("activityName", "?")
        if self._send_favorite_key(device_id, key_id):
            self.logger.info("Sent favorite key %d (device %d) for '%s'" % (key_id, device_id, act_name))
        else:
            self.logger.error("Failed to send favorite key for '%s'" % act_name)

    def refreshActivities(self, action):
        self.logger.info("Refreshing activities from hub...")
        self._request_activity_list()

    def stopAllActivities(self, action):
        self.logger.info("Stopping all activities")
        topic = "activity/%s/activity_control_down" % self.hubMac
        self._publish(topic, {"data": {"activity_id": 255, "state": "off"}})

    # -------------------------------------------------------------------------
    # Menu item callbacks
    # -------------------------------------------------------------------------

    def discoverHub(self):
        self.logger.info("Searching for Sofabaton hub via mDNS...")
        try:
            from zeroconf import Zeroconf, ServiceBrowser

            found = []

            class Listener:
                def add_service(self, zc, stype, name):
                    info = zc.get_service_info(stype, name)
                    if info:
                        props = {}
                        if info.properties:
                            props = {k.decode(): v.decode() for k, v in info.properties.items()}
                        found.append({
                            "name": name,
                            "host": info.server,
                            "port": info.port,
                            "mac": props.get("MAC", ""),
                            "properties": props,
                        })

                def remove_service(self, zc, stype, name):
                    pass

                def update_service(self, zc, stype, name):
                    pass

            zc = Zeroconf()
            listener = Listener()
            ServiceBrowser(zc, "_sofabaton_hub._udp.local.", listener)
            time.sleep(3)
            zc.close()

            if found:
                hub = found[0]
                mac = hub["mac"].upper().replace(":", "").replace("-", "")
                self.logger.info(
                    "Found Sofabaton hub: %s (MAC: %s, host: %s)"
                    % (hub["name"], mac, hub["host"])
                )
                if len(found) > 1:
                    for h in found[1:]:
                        self.logger.info(
                            "Also found: %s (MAC: %s, host: %s)"
                            % (h["name"], h["mac"], h["host"])
                        )
                # Auto-save MAC to plugin prefs
                if mac and mac != self.hubMac:
                    self.hubMac = mac
                    self.pluginPrefs["hubMac"] = mac
                    self.logger.info("Hub MAC saved to plugin preferences: %s" % mac)
                    # Connect with the discovered MAC
                    if not self._mqtt_connected:
                        self._start_mqtt()
                    else:
                        self._stop_mqtt()
                        self._start_mqtt()
            else:
                self.logger.info("No Sofabaton hubs found. Ensure hub is on the same network.")

        except ImportError as exc:
            self.logger.error("zeroconf import failed: %s" % exc)
        except Exception as exc:
            self.logger.error("mDNS discovery failed: %s" % exc)
            self.logger.exception(exc)

    def refreshActivitiesMenu(self):
        if not self._mqtt_connected:
            self.logger.error("Not connected to MQTT broker")
            return
        self.logger.info("Requesting activity list from hub...")
        self._request_activity_list()

    def listMacroKeys(self):
        if not self._mqtt_connected:
            self.logger.error("Not connected to MQTT broker")
            return
        self.logger.info("Requesting macro keys for all activities...")
        for act_id in self._activities:
            topic = "activity/%s/macro_keys_request" % self.hubMac
            self._publish(topic, {"data": {"activity_id": act_id}})

    def listFavoriteKeys(self):
        if not self._mqtt_connected:
            self.logger.error("Not connected to MQTT broker")
            return
        self.logger.info("Requesting favorite keys for all activities...")
        for act_id in self._activities:
            topic = "activity/%s/favorites_keys_request" % self.hubMac
            self._publish(topic, {"data": {"activity_id": act_id}})

    # -------------------------------------------------------------------------
    # Config validation
    # -------------------------------------------------------------------------

    def validatePrefsConfigUi(self, valuesDict):
        errorsDict = {}

        # Validate broker host
        host = valuesDict.get("mqttBrokerHost", "").strip()
        if not host:
            errorsDict["mqttBrokerHost"] = "Broker host is required"

        # Validate broker port
        try:
            port = int(valuesDict.get("mqttBrokerPort", 1883))
            if port < 1 or port > 65535:
                errorsDict["mqttBrokerPort"] = "Port must be 1-65535"
        except ValueError:
            errorsDict["mqttBrokerPort"] = "Must be a number"

        # Validate MAC address
        mac = valuesDict.get("hubMac", "").upper().replace(":", "").replace("-", "")
        if mac and len(mac) != 12:
            errorsDict["hubMac"] = "MAC address must be 12 hex characters"
        elif mac:
            try:
                int(mac, 16)
            except ValueError:
                errorsDict["hubMac"] = "MAC address must be hexadecimal"

        if errorsDict:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if userCancelled:
            return

        self.debug = valuesDict.get("showDebugInfo", False)
        self.logMqtt = valuesDict.get("logMqtt", False)

        new_host = valuesDict.get("mqttBrokerHost", "localhost")
        new_port = int(valuesDict.get("mqttBrokerPort", 1883))
        new_user = valuesDict.get("mqttUsername", "")
        new_pass = valuesDict.get("mqttPassword", "")
        new_mac = valuesDict.get("hubMac", "").upper().replace(":", "").replace("-", "")
        self.logger.info("Config saved — broker: %s:%d, MAC: '%s'" % (new_host, new_port, new_mac))
        self.autoDiscover = valuesDict.get("autoDiscover", True)

        reconnect_needed = (
            new_host != self.brokerHost
            or new_port != self.brokerPort
            or new_user != self.mqttUsername
            or new_pass != self.mqttPassword
            or new_mac != self.hubMac
        )

        self.brokerHost = new_host
        self.brokerPort = new_port
        self.mqttUsername = new_user
        self.mqttPassword = new_pass
        self.hubMac = new_mac

        if reconnect_needed:
            self.logger.info("Configuration changed, reconnecting to MQTT...")
            self._stop_mqtt()
            self._start_mqtt()

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errorsDict = {}

        if typeId == "sofabatonHub":
            mac = valuesDict.get("macAddress", "").upper().replace(":", "").replace("-", "")
            if not mac:
                errorsDict["macAddress"] = "MAC address is required"
            elif len(mac) != 12:
                errorsDict["macAddress"] = "MAC address must be 12 hex characters"
            else:
                try:
                    int(mac, 16)
                except ValueError:
                    errorsDict["macAddress"] = "MAC address must be hexadecimal"

        if errorsDict:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)
