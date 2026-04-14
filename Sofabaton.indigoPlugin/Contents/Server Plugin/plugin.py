#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Sofabaton Hub - Indigo Plugin
# Controls Sofabaton X2 (MQTT) and X1/X1S (TCP) universal remote hubs
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
        self.deviceFolderId = int(pluginPrefs.get("deviceFolder", 0))

        # MQTT client
        self._mqtt = None
        self._mqtt_connected = False
        self._mqtt_lock = threading.Lock()
        self._publish_lock = threading.Lock()

        # Activity tracking (accessed from MQTT thread and X1 TCP thread)
        self._activities = {}  # activity_id -> {"name": str, "state": str}
        self._activities_lock = threading.Lock()
        self._pending_requests = {}  # topic -> callback

        # Dedup cache: prevent processing duplicate messages
        self._recent_messages = {}  # topic -> (payload_hash, timestamp)
        self.DEDUP_SECONDS = 5

        # Hub device references
        self._hub_dev_id = None
        self._x1_transport = None
        self._x1_hub_dev_id = None

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

        # Find or create hub device
        for dev in indigo.devices.iter("self.sofabatonHub"):
            self._hub_dev_id = dev.id
            break

        if not self._hub_dev_id:
            self._create_hub_device()

        self._start_mqtt()

        # Also start X1/X1S transport if configured
        for dev in indigo.devices.iter("self.sofabatonX1Hub"):
            self._x1_hub_dev_id = dev.id
            self._start_x1_transport(dev)
            break

    def shutdown(self):
        self.logger.info("Sofabaton plugin stopping")
        self._stop_mqtt()
        self._stop_x1_transport()

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

        elif dev.deviceTypeId == "sofabatonX1Hub":
            self._x1_hub_dev_id = dev.id
            if self._x1_transport is None:
                self._start_x1_transport(dev)

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
            except Exception as exc:
                self.logger.debug("Error stopping MQTT client: %s" % exc)
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

        with self._activities_lock:
            # Remove only X2 activities (keyed by hub_dev_id), then add fresh ones
            x2_ids = {aid for aid, info in self._activities.items()
                       if info.get("_hub_dev_id") == self._hub_dev_id}
            for aid in x2_ids:
                del self._activities[aid]
            for act in activities:
                act_id = act.get("activity_id")
                act_name = act.get("activity_name", "Activity %d" % act_id)
                act_state = act.get("state", "off")
                self._activities[act_id] = {"name": act_name, "state": act_state,
                                            "_hub_dev_id": self._hub_dev_id}

            # Create or update Indigo devices for each activity
            self._sync_activity_devices(hub_dev_id=self._hub_dev_id)

    def _handle_activity_state(self, payload):
        act_id = payload.get("activity_id")
        state = payload.get("state", "off")

        with self._activities_lock:
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
                self.logger.info("Unknown activity %s detected, requesting updated list" % act_id)
                self._request_activity_list()
                return

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

    def _create_hub_device(self):
        try:
            create_kwargs = {
                "protocol": indigo.kProtocol.Plugin,
                "deviceTypeId": "sofabatonHub",
                "name": "Sofabaton Hub",
                "props": {"macAddress": self.hubMac},
            }
            if self.deviceFolderId:
                create_kwargs["folder"] = self.deviceFolderId
            hub_dev = indigo.device.create(**create_kwargs)
            self._hub_dev_id = hub_dev.id
            hub_dev.updateStateOnServer("activeActivity", "off")
            hub_dev.updateStateOnServer("activeActivityId", 0)
            hub_dev.updateStateOnServer("connectionStatus", "disconnected")
            hub_dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            self.logger.info("Created hub device: %s" % hub_dev.name)
        except Exception as exc:
            self.logger.error("Failed to create hub device: %s" % exc)

    def _sync_activity_devices(self, hub_dev_id=None):
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
                    "hubDevice": str(hub_dev_id) if hub_dev_id else "",
                }
                try:
                    create_kwargs = {
                        "protocol": indigo.kProtocol.Plugin,
                        "deviceTypeId": "sofabatonActivity",
                        "name": dev_name,
                        "props": props,
                    }
                    if self.deviceFolderId:
                        create_kwargs["folder"] = self.deviceFolderId
                    new_dev = indigo.device.create(**create_kwargs)
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
            except Exception as exc:
                self.logger.debug("Failed to update hub connection state: %s" % exc)

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
                        {"key": "activeActivity", "value": "off"},
                        {"key": "activeActivityId", "value": 0},
                    ])
            except Exception as exc:
                self.logger.debug("Failed to update hub active activity: %s" % exc)

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
    # X1/X1S TCP transport management
    # -------------------------------------------------------------------------

    def _start_x1_transport(self, dev):
        """Create and start the TCP transport for an X1/X1S hub device."""
        hub_ip = dev.pluginProps.get("hubIp", "")
        hub_mac = dev.pluginProps.get("macAddress", "")
        hub_model = dev.pluginProps.get("hubModel", "X1S")
        listen_port = int(dev.pluginProps.get("listenPort", 8200))

        if not hub_ip:
            self.logger.warning("X1 hub IP not configured, cannot start transport")
            return

        try:
            from transport_tcp import TcpTransport
        except ImportError as exc:
            self.logger.error("transport_tcp import failed: %s" % exc)
            return

        self.logger.info("Starting X1 transport for %s hub at %s" % (hub_model, hub_ip))
        self._x1_transport = TcpTransport(
            hub_ip=hub_ip,
            hub_mac=hub_mac,
            logger=self.logger,
            listen_port_base=listen_port,
            hub_model=hub_model,
            on_activity_update=self._on_x1_activity_update,
            on_connection_change=self._on_x1_connection_change,
        )
        try:
            self._x1_transport.connect()
        except Exception as exc:
            self.logger.error("X1 transport connect failed: %s" % exc)
            self._x1_transport = None

    def _stop_x1_transport(self):
        """Stop the X1/X1S TCP transport."""
        if self._x1_transport is not None:
            try:
                self._x1_transport.disconnect()
            except Exception as exc:
                self.logger.debug("Error stopping X1 transport: %s" % exc)
            self._x1_transport = None

    def _on_x1_activity_update(self, activities):
        """Callback from TcpTransport when activity catalog is updated."""
        with self._activities_lock:
            # Remove only X1 activities, then merge fresh ones
            x1_ids = {aid for aid, info in self._activities.items()
                       if info.get("_hub_dev_id") == self._x1_hub_dev_id}
            for aid in x1_ids:
                del self._activities[aid]
            for act_id, act_info in activities.items():
                self._activities[act_id] = {
                    "name": act_info["name"],
                    "state": "on" if act_info.get("active", False) else "off",
                    "_hub_dev_id": self._x1_hub_dev_id,
                }
            self.logger.debug("X1 activity update: %d activities" % len(activities))
            self._sync_activity_devices(hub_dev_id=self._x1_hub_dev_id)
            # Update X1 hub states (inside lock so _activities is consistent)
            active_id = None
            for act_id, act_info in self._activities.items():
                if act_info.get("_hub_dev_id") == self._x1_hub_dev_id and act_info["state"] == "on":
                    active_id = act_id
                    break
            self._update_x1_hub_states(active_id)

    def _on_x1_connection_change(self, status):
        """Callback from TcpTransport when connection state changes."""
        self.logger.info("X1 hub connection: %s" % status)
        if self._x1_hub_dev_id:
            try:
                dev = indigo.devices[self._x1_hub_dev_id]
                dev.updateStateOnServer("connectionStatus", status, uiValue=status.title())
                if status == "connected":
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                else:
                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            except Exception as exc:
                self.logger.debug("Failed to update X1 connection state: %s" % exc)

    def _update_x1_hub_states(self, active_act_id):
        """Update X1 hub device states (active activity and device count)."""
        if not self._x1_hub_dev_id:
            return
        try:
            dev = indigo.devices[self._x1_hub_dev_id]
            device_count = len(self._x1_transport.devices) if self._x1_transport else 0
            if active_act_id and active_act_id in self._activities:
                name = self._activities[active_act_id]["name"]
                dev.updateStatesOnServer([
                    {"key": "activeActivity", "value": name},
                    {"key": "activeActivityId", "value": active_act_id},
                    {"key": "deviceCount", "value": device_count},
                ])
            else:
                dev.updateStatesOnServer([
                    {"key": "activeActivity", "value": "off"},
                    {"key": "activeActivityId", "value": 0},
                    {"key": "deviceCount", "value": device_count},
                ])
        except Exception as exc:
            self.logger.debug("Failed to update X1 hub states: %s" % exc)

    def _get_transport_for_activity(self, dev):
        """Determine which transport an activity device uses ('x1' or 'mqtt')."""
        hub_dev_id_str = dev.pluginProps.get("hubDevice", "")
        if hub_dev_id_str and self._x1_hub_dev_id:
            try:
                if int(hub_dev_id_str) == self._x1_hub_dev_id:
                    return "x1"
            except (ValueError, TypeError):
                pass
        return "mqtt"

    def _send_activity_command(self, act_id, state, transport_type):
        """Route an activity on/off command to the correct transport."""
        if transport_type == "x1":
            if not self._x1_transport or not self._x1_transport.is_connected():
                self.logger.error("X1 hub not connected")
                return False
            if state == "on":
                return self._x1_transport.activate(act_id)
            else:
                return self._x1_transport.deactivate(act_id)
        else:
            return self._send_activity_control(act_id, state)

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
        transport_type = self._get_transport_for_activity(dev)

        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            if self._send_activity_command(act_id, "on", transport_type):
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
            if self._send_activity_command(act_id, "off", transport_type):
                self.logger.info("Deactivated '%s'" % act_name)
                dev.updateStateOnServer("onOffState", False)
                dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                self._update_hub_active_activity(None)
            else:
                self.logger.error("Failed to deactivate '%s'" % act_name)

        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            new_state = not dev.onState
            if self._send_activity_command(act_id, "on" if new_state else "off", transport_type):
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
            if transport_type == "x1":
                if self._x1_transport and self._x1_transport.is_connected():
                    self._x1_transport.request_activities()
            else:
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

    def sendKeyToCurrentActivity(self, action):
        # Find the currently active activity
        active_id = None
        active_name = None
        active_hub = None
        with self._activities_lock:
            for act_id, act_info in self._activities.items():
                if act_info["state"] == "on":
                    active_id = act_id
                    active_name = act_info["name"]
                    active_hub = act_info.get("_hub_dev_id")
                    break
        if active_id is None:
            self.logger.error("No activity is currently active")
            return

        # X1/X1S activities don't use the MQTT key-id scheme — route users to
        # the Send Device Command action, which is the X1 equivalent.
        if active_hub == self._x1_hub_dev_id:
            self.logger.error(
                "'Send Key to Current Activity' is X2-only. "
                "For X1/X1S activities use the 'Send Device Command' action."
            )
            return

        key_name = action.props.get("keyName", "ok")
        key_id = KEY_IDS.get(key_name)
        if key_id is None:
            self.logger.error("Unknown key name: %s" % key_name)
            return
        if self._send_key_control(active_id, key_id):
            self.logger.info("Sent '%s' key to current activity '%s'" % (key_name, active_name))
        else:
            self.logger.error("Failed to send '%s' key" % key_name)

    def refreshActivities(self, action):
        self.logger.info("Refreshing activities from hub...")
        self._request_activity_list()

    def stopAllActivities(self, action):
        self.logger.info("Stopping all activities")

        # X2 path: single broadcast via MQTT (activity_id 255 = all).
        if self._mqtt_connected and self.hubMac:
            topic = "activity/%s/activity_control_down" % self.hubMac
            self._publish(topic, {"data": {"activity_id": 255, "state": "off"}})

        # X1/X1S path: no broadcast equivalent, so iterate live X1 activities
        # and deactivate each one that is currently on.
        if self._x1_transport and self._x1_transport.is_connected():
            with self._activities_lock:
                x1_active = [
                    aid for aid, info in self._activities.items()
                    if info.get("_hub_dev_id") == self._x1_hub_dev_id
                    and info.get("state") == "on"
                ]
            for aid in x1_active:
                if not self._x1_transport.deactivate(aid):
                    self.logger.error("Failed to deactivate X1 activity %s" % aid)

    def sendDeviceCommand(self, action):
        """Send a device command via the X1/X1S hub."""
        if not self._x1_transport or not self._x1_transport.is_connected():
            self.logger.error("X1 hub not connected")
            return

        try:
            act_id = int(action.props.get("targetActivityId", 0))
            dev_id = int(action.props.get("targetDeviceId", 0))
            cmd_id = int(action.props.get("targetCommandId", 0))
        except (ValueError, TypeError):
            self.logger.error("Invalid activity, device, or command ID")
            return

        if self._x1_transport.send_command(act_id, dev_id, cmd_id):
            self.logger.info(
                "Sent command %d to device %d in activity %d" % (cmd_id, dev_id, act_id)
            )
        else:
            self.logger.error(
                "Failed to send command %d to device %d" % (cmd_id, dev_id)
            )

    def getX1ActivityList(self, filter="", valuesDict=None, typeId="", targetId=0):
        """Dynamic list callback: X1 activities."""
        items = []
        if self._x1_transport:
            for act_id, act_info in sorted(self._x1_transport.activities.items()):
                items.append((str(act_id), act_info["name"]))
        if not items:
            items.append(("", "— No activities —"))
        return items

    def getX1DeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        """Dynamic list callback: X1 devices."""
        items = []
        if self._x1_transport:
            for dev_id, dev_info in sorted(self._x1_transport.devices.items()):
                items.append((str(dev_id), dev_info["name"]))
        if not items:
            items.append(("", "— No devices —"))
        return items

    def getX1CommandList(self, filter="", valuesDict=None, typeId="", targetId=0):
        """Dynamic list callback: X1 commands (filtered by selected device)."""
        items = []
        if self._x1_transport and valuesDict:
            try:
                dev_id = int(valuesDict.get("targetDeviceId", 0))
            except (ValueError, TypeError):
                dev_id = 0
            commands = self._x1_transport.commands.get(dev_id, [])
            for cmd in commands:
                label = cmd.get("label", "Command %d" % cmd["command_id"])
                items.append((str(cmd["command_id"]), label))
        if not items:
            items.append(("", "— No commands —"))
        return items

    # -------------------------------------------------------------------------
    # Menu item callbacks
    # -------------------------------------------------------------------------

    def discoverHub(self):
        self.logger.info("Searching for Sofabaton hubs via mDNS...")
        try:
            from zeroconf import Zeroconf, ServiceBrowser
            from protocol_const import MDNS_X1, MDNS_X2, HUB_VERSIONS

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
                            "stype": stype,
                        })

                def remove_service(self, zc, stype, name):
                    pass

                def update_service(self, zc, stype, name):
                    pass

            zc = Zeroconf()
            listener = Listener()
            ServiceBrowser(zc, MDNS_X2, listener)
            ServiceBrowser(zc, MDNS_X1, listener)
            time.sleep(3)
            zc.close()

            if found:
                for hub in found:
                    mac = hub["mac"].upper().replace(":", "").replace("-", "")
                    hver = hub["properties"].get("HVER", "")
                    model = HUB_VERSIONS.get(hver, "Unknown")
                    ip = hub["host"].rstrip(".")
                    self.logger.info(
                        "Found Sofabaton %s hub: %s (MAC: %s, host: %s)"
                        % (model, hub["name"], mac, ip)
                    )
                    self._create_discovered_hub(hub, mac)
            else:
                self.logger.info("No Sofabaton hubs found. Ensure hub is on the same network.")

        except ImportError as exc:
            self.logger.error("zeroconf import failed: %s" % exc)
        except Exception as exc:
            self.logger.error("mDNS discovery failed: %s" % exc)
            self.logger.exception(exc)

    def _create_discovered_hub(self, hub_info, mac):
        """Create or update an Indigo device for a discovered hub."""
        from protocol_const import HUB_VERSIONS

        hver = hub_info["properties"].get("HVER", "")
        model = HUB_VERSIONS.get(hver, "Unknown")
        ip = hub_info["host"].rstrip(".")

        if model in ("X1", "X1S"):
            # X1/X1S hub — uses TCP transport
            device_type = "sofabatonX1Hub"
            # Check if hub already exists by MAC
            for dev in indigo.devices.iter("self.sofabatonX1Hub"):
                if dev.pluginProps.get("macAddress", "").upper() == mac:
                    self.logger.info("X1 hub already exists: %s" % dev.name)
                    # Update IP if changed
                    if dev.pluginProps.get("hubIp", "") != ip:
                        props = dev.pluginProps
                        props["hubIp"] = ip
                        dev.replacePluginPropsOnServer(props)
                        self.logger.info("Updated hub IP to %s" % ip)
                    return

            dev_name = "Sofabaton %s Hub" % model
            props = {
                "hubIp": ip,
                "macAddress": mac,
                "hubModel": model,
                "listenPort": "8200",
            }
            try:
                create_kwargs = {
                    "protocol": indigo.kProtocol.Plugin,
                    "deviceTypeId": device_type,
                    "name": dev_name,
                    "props": props,
                }
                if self.deviceFolderId:
                    create_kwargs["folder"] = self.deviceFolderId
                new_dev = indigo.device.create(**create_kwargs)
                new_dev.updateStateOnServer("connectionStatus", "disconnected")
                new_dev.updateStateOnServer("activeActivity", "off")
                new_dev.updateStateOnServer("activeActivityId", 0)
                new_dev.updateStateOnServer("hubModel", model)
                new_dev.updateStateOnServer("deviceCount", 0)
                new_dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                self.logger.info("Created %s hub device: %s (IP: %s)" % (model, dev_name, ip))
            except Exception as exc:
                self.logger.error("Failed to create X1 hub device: %s" % exc)

        else:
            # X2 hub — uses MQTT transport
            if mac and mac != self.hubMac:
                self.hubMac = mac
                self.pluginPrefs["hubMac"] = mac
                self.logger.info("Hub MAC saved to plugin preferences: %s" % mac)
                if not self._mqtt_connected:
                    self._start_mqtt()
                else:
                    self._stop_mqtt()
                    self._start_mqtt()

    def refreshActivitiesMenu(self):
        refreshed = False
        if self._x1_transport and self._x1_transport.is_connected():
            self.logger.info("Requesting catalogs from X1 hub...")
            self._x1_transport.request_devices()
            self._x1_transport.request_activities()
            refreshed = True
        if self._mqtt_connected:
            self.logger.info("Requesting activity list from X2 hub...")
            self._request_activity_list()
            refreshed = True
        if not refreshed:
            self.logger.error("No hub connections available")

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

    def listX1Devices(self):
        """Log all X1 devices from the cached catalog."""
        if not self._x1_transport:
            self.logger.error("X1 hub not configured")
            return
        devices = self._x1_transport.devices
        if not devices:
            self.logger.info("No X1 devices cached. Hub may not be connected yet.")
            return
        self.logger.info("=== X1 Devices (%d) ===" % len(devices))
        for dev_id, dev_info in sorted(devices.items()):
            self.logger.info("  [%d] %s" % (dev_id, dev_info["name"]))
        self.logger.info("=== End X1 Devices ===")

    def listX1Commands(self):
        """Log all X1 commands for all devices, requesting them if not cached."""
        if not self._x1_transport:
            self.logger.error("X1 hub not configured")
            return
        if not self._x1_transport.is_connected():
            self.logger.error("X1 hub not connected")
            return

        devices = self._x1_transport.devices
        commands = self._x1_transport.commands
        if not devices:
            self.logger.info("No X1 devices cached. Requesting device list...")
            self._x1_transport.request_devices()
            return

        # If commands are cached, log them; otherwise request them
        if commands:
            self.logger.info("=== X1 Commands ===")
            for dev_id, cmd_list in sorted(commands.items()):
                dev_name = devices.get(dev_id, {}).get("name", "Device %d" % dev_id)
                self.logger.info("  Device: %s [%d]" % (dev_name, dev_id))
                for cmd in cmd_list:
                    label = cmd.get("label", "")
                    self.logger.info("    [%d] %s" % (cmd["command_id"], label))
            self.logger.info("=== End X1 Commands ===")
        else:
            self.logger.info("Requesting commands for %d devices..." % len(devices))
            for dev_id in devices:
                self._x1_transport.request_commands(dev_id)

    def dumpConfig(self):
        self.logger.info("=== Sofabaton Hub Configuration ===")
        self.logger.info("Hub MAC: %s" % self.hubMac)
        self.logger.info("MQTT Broker: %s:%d" % (self.brokerHost, self.brokerPort))
        self.logger.info("Connected: %s" % self._mqtt_connected)
        self.logger.info("--- Activities (%d) ---" % len(self._activities))
        for act_id, act_info in sorted(self._activities.items()):
            self.logger.info("  [%d] %s (state: %s)" % (act_id, act_info["name"], act_info["state"]))
        self.logger.info("--- Indigo Devices ---")
        for dev in indigo.devices.iter("self"):
            self.logger.info("  %s (type: %s, id: %d)" % (dev.name, dev.deviceTypeId, dev.id))
        self.logger.info("=== End Configuration ===")
        # Also request device list from hub
        if self._mqtt_connected:
            topic = "device/%s/list_request" % self.hubMac
            self._publish(topic, {"data": "device_list"})

    # -------------------------------------------------------------------------
    # Dynamic list callbacks
    # -------------------------------------------------------------------------

    def getDeviceFolderList(self, filter="", valuesDict=None, typeId="", targetId=0):
        folder_list = [(0, "— No Folder —")]
        for folder in indigo.devices.folders:
            folder_list.append((folder.id, folder.name))
        folder_list.sort(key=lambda x: x[1].lower() if x[0] != 0 else "")
        return folder_list

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
        self.deviceFolderId = int(valuesDict.get("deviceFolder", 0))

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
