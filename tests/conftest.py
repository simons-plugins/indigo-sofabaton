"""Shared pytest fixtures for Sofabaton plugin tests."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock

import pytest

# Mock the indigo module before importing plugin
indigo_mock = MagicMock()
indigo_mock.PluginBase = object
indigo_mock.kProtocol.Plugin = "Plugin"
indigo_mock.kDeviceAction.TurnOn = 1
indigo_mock.kDeviceAction.TurnOff = 2
indigo_mock.kDeviceAction.Toggle = 3
indigo_mock.kDeviceAction.RequestStatus = 4
indigo_mock.kStateImageSel.PowerOn = "PowerOn"
indigo_mock.kStateImageSel.PowerOff = "PowerOff"
indigo_mock.kStateImageSel.SensorOn = "SensorOn"
indigo_mock.kStateImageSel.SensorOff = "SensorOff"
indigo_mock.kStateImageSel.Error = "Error"
sys.modules["indigo"] = indigo_mock

# Add Server Plugin directory to path
SERVER_PLUGIN_DIR = (
    Path(__file__).parent.parent
    / "Sofabaton.indigoPlugin"
    / "Contents"
    / "Server Plugin"
)
sys.path.insert(0, str(SERVER_PLUGIN_DIR))

from plugin import Plugin, KEY_IDS, PUBLISH_DELAY


# =============================================================================
# Mock Indigo Device
# =============================================================================

class MockIndigoDevice:
    """Mock Indigo device with state tracking."""

    def __init__(self, dev_id, name="Test Device", device_type_id="sofabatonActivity",
                 plugin_props=None, states=None):
        self.id = dev_id
        self.name = name
        self.deviceTypeId = device_type_id
        self._plugin_props = plugin_props or {}
        self.states = states or {}
        self.onState = False
        self._state_image = None
        self._error_state = None
        self._states_updated = []

    @property
    def pluginProps(self):
        return dict(self._plugin_props)

    def updateStateOnServer(self, key, value, uiValue=None, clearErrorState=False):
        self.states[key] = value
        if key == "onOffState":
            self.onState = value

    def updateStatesOnServer(self, state_list):
        for s in state_list:
            self.updateStateOnServer(s["key"], s["value"])

    def updateStateImageOnServer(self, image):
        self._state_image = image

    def setErrorStateOnServer(self, msg):
        self._error_state = msg

    def stateListOrDisplayStateIdChanged(self):
        pass

    def replacePluginPropsOnServer(self, props):
        self._plugin_props = dict(props)


# =============================================================================
# Mock MQTT Message
# =============================================================================

class MockMQTTMessage:
    """Mock paho-mqtt message."""

    def __init__(self, topic, payload):
        self.topic = topic
        if isinstance(payload, dict):
            self.payload = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            self.payload = payload.encode("utf-8")
        else:
            self.payload = payload


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.exception = Mock()
    return logger


@pytest.fixture
def default_prefs():
    """Default plugin preferences."""
    return {
        "showDebugInfo": False,
        "logMqtt": False,
        "mqttBrokerHost": "192.168.0.2",
        "mqttBrokerPort": "1883",
        "mqttUsername": "",
        "mqttPassword": "",
        "hubMac": "206EF1241808",
        "autoDiscover": True,
        "deviceFolder": "0",
    }


@pytest.fixture
def plugin(default_prefs, mock_logger):
    """Create a Plugin instance with mocked dependencies."""
    with patch.object(Plugin, "__init__", lambda self, *a, **kw: None):
        p = Plugin.__new__(Plugin)

    # Manually init the attributes that __init__ would set
    p.debug = default_prefs.get("showDebugInfo", False)
    p.logMqtt = default_prefs.get("logMqtt", False)
    p.brokerHost = default_prefs.get("mqttBrokerHost", "localhost")
    p.brokerPort = int(default_prefs.get("mqttBrokerPort", 1883))
    p.mqttUsername = default_prefs.get("mqttUsername", "")
    p.mqttPassword = default_prefs.get("mqttPassword", "")
    p.hubMac = default_prefs.get("hubMac", "").upper().replace(":", "").replace("-", "")
    p.autoDiscover = default_prefs.get("autoDiscover", True)
    p.deviceFolderId = int(default_prefs.get("deviceFolder", 0))
    p._mqtt = MagicMock()
    p._mqtt_connected = True
    p._mqtt_lock = MagicMock()
    p._publish_lock = MagicMock()
    p._activities = {}
    p._pending_requests = {}
    p._recent_messages = {}
    p.DEDUP_SECONDS = 5
    p._hub_dev_id = 100
    p.logger = mock_logger
    p.pluginPrefs = dict(default_prefs)

    return p


@pytest.fixture
def hub_device():
    """Create a mock hub device."""
    return MockIndigoDevice(
        dev_id=100,
        name="Sofabaton Hub",
        device_type_id="sofabatonHub",
        plugin_props={"macAddress": "206EF1241808"},
        states={"connectionStatus": "connected", "activeActivity": "off", "activeActivityId": 0},
    )


@pytest.fixture
def activity_device():
    """Create a mock activity device."""
    return MockIndigoDevice(
        dev_id=201,
        name="Sofabaton - Watch TV",
        device_type_id="sofabatonActivity",
        plugin_props={"activityId": "1", "activityName": "Watch TV", "hubDevice": "100"},
        states={"onOffState": False},
    )


@pytest.fixture
def activity_list_payload():
    """Sample activity list MQTT payload."""
    return {
        "data": [
            {"activity_id": 1, "activity_name": "Watch TV", "state": "off"},
            {"activity_id": 2, "activity_name": "Listen to Music", "state": "off"},
            {"activity_id": 3, "activity_name": "Play Games", "state": "on"},
        ]
    }


@pytest.fixture
def keys_list_payload():
    """Sample keys list MQTT payload."""
    return {
        "activity_id": 1,
        "data": [
            {"key_id": 174},
            {"key_id": 178},
            {"key_id": 176},
        ]
    }


@pytest.fixture
def macro_keys_payload():
    """Sample macro keys MQTT payload."""
    return {
        "activity_id": 1,
        "data": [
            {"key_id": 100, "key_name": "Power On Sequence"},
            {"key_id": 101, "key_name": "Night Mode"},
        ]
    }


@pytest.fixture
def favorites_keys_payload():
    """Sample favorites keys MQTT payload."""
    return {
        "activity_id": 1,
        "data": [
            {"key_id": 200, "key_name": "BBC One", "device_id": 5},
            {"key_id": 201, "key_name": "Netflix", "device_id": 5},
        ]
    }
