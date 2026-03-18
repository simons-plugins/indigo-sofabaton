"""Tests for X1/X1S integration — activity sync, transport routing,
dynamic lists, and connection callbacks."""
from unittest.mock import patch, MagicMock

from conftest import MockIndigoDevice


class TestOnX1ActivityUpdate:
    """Tests for _on_x1_activity_update() populating _activities."""

    def test_populates_activities_dict(self, plugin):
        """Activities dict is populated from the X1 callback payload."""
        activities = {
            10: {"name": "Watch TV", "active": True},
            20: {"name": "Listen to Music", "active": False},
        }
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        plugin._on_x1_activity_update(activities)

        assert len(plugin._activities) == 2
        assert plugin._activities[10] == {"name": "Watch TV", "state": "on"}
        assert plugin._activities[20] == {"name": "Listen to Music", "state": "off"}

    def test_inactive_activities_get_off_state(self, plugin):
        """Activities without active=True get state 'off'."""
        activities = {
            1: {"name": "Activity A"},
        }
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        plugin._on_x1_activity_update(activities)

        assert plugin._activities[1]["state"] == "off"

    def test_calls_sync_activity_devices(self, plugin):
        """After populating activities, _sync_activity_devices is called."""
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        plugin._on_x1_activity_update({5: {"name": "Test", "active": False}})

        plugin._sync_activity_devices.assert_called_once()

    def test_calls_update_x1_hub_states_with_active_id(self, plugin):
        """Hub states are updated with the active activity id."""
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        activities = {
            10: {"name": "A", "active": False},
            20: {"name": "B", "active": True},
        }
        plugin._on_x1_activity_update(activities)

        plugin._update_x1_hub_states.assert_called_once_with(20)

    def test_calls_update_x1_hub_states_with_none_when_nothing_active(self, plugin):
        """Hub states are updated with None when no activity is active."""
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        plugin._on_x1_activity_update({1: {"name": "A", "active": False}})

        plugin._update_x1_hub_states.assert_called_once_with(None)

    def test_replaces_previous_activities(self, plugin):
        """Each call replaces the entire activities dict."""
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()
        plugin._activities = {99: {"name": "Old", "state": "on"}}

        plugin._on_x1_activity_update({1: {"name": "New", "active": False}})

        assert 99 not in plugin._activities
        assert 1 in plugin._activities

    def test_empty_activities(self, plugin):
        """Empty activities dict results in empty _activities."""
        plugin._sync_activity_devices = MagicMock()
        plugin._update_x1_hub_states = MagicMock()

        plugin._on_x1_activity_update({})

        assert plugin._activities == {}


class TestGetTransportForActivity:
    """Tests for _get_transport_for_activity() routing."""

    def test_returns_x1_for_x1_hub_activity(self, plugin):
        """Activity linked to X1 hub returns 'x1' transport."""
        plugin._x1_hub_dev_id = 200
        dev = MockIndigoDevice(
            301, device_type_id="sofabatonActivity",
            plugin_props={"hubDevice": "200", "activityId": "1"},
        )
        assert plugin._get_transport_for_activity(dev) == "x1"

    def test_returns_mqtt_for_x2_hub_activity(self, plugin):
        """Activity linked to X2 hub returns 'mqtt' transport."""
        plugin._x1_hub_dev_id = 200
        dev = MockIndigoDevice(
            301, device_type_id="sofabatonActivity",
            plugin_props={"hubDevice": "100", "activityId": "1"},
        )
        assert plugin._get_transport_for_activity(dev) == "mqtt"

    def test_returns_mqtt_when_no_x1_hub(self, plugin):
        """When no X1 hub is configured, always returns 'mqtt'."""
        plugin._x1_hub_dev_id = None
        dev = MockIndigoDevice(
            301, device_type_id="sofabatonActivity",
            plugin_props={"hubDevice": "200", "activityId": "1"},
        )
        assert plugin._get_transport_for_activity(dev) == "mqtt"

    def test_returns_mqtt_when_hub_device_empty(self, plugin):
        """Activity with empty hubDevice prop returns 'mqtt'."""
        plugin._x1_hub_dev_id = 200
        dev = MockIndigoDevice(
            301, device_type_id="sofabatonActivity",
            plugin_props={"hubDevice": "", "activityId": "1"},
        )
        assert plugin._get_transport_for_activity(dev) == "mqtt"

    def test_returns_mqtt_when_hub_device_invalid(self, plugin):
        """Activity with non-numeric hubDevice returns 'mqtt'."""
        plugin._x1_hub_dev_id = 200
        dev = MockIndigoDevice(
            301, device_type_id="sofabatonActivity",
            plugin_props={"hubDevice": "invalid", "activityId": "1"},
        )
        assert plugin._get_transport_for_activity(dev) == "mqtt"


class TestGetX1ActivityList:
    """Tests for getX1ActivityList() dynamic list callback."""

    def test_returns_activities_from_transport(self, plugin):
        """Returns menu items from X1 transport activities."""
        transport = MagicMock()
        transport.activities = {
            1: {"name": "Watch TV"},
            2: {"name": "Music"},
        }
        plugin._x1_transport = transport

        result = plugin.getX1ActivityList()

        assert (str(1), "Watch TV") in result
        assert (str(2), "Music") in result

    def test_returns_placeholder_when_no_transport(self, plugin):
        """Returns placeholder when no X1 transport is connected."""
        plugin._x1_transport = None

        result = plugin.getX1ActivityList()

        assert len(result) == 1
        assert result[0][0] == ""

    def test_returns_placeholder_when_no_activities(self, plugin):
        """Returns placeholder when transport has no activities."""
        transport = MagicMock()
        transport.activities = {}
        plugin._x1_transport = transport

        result = plugin.getX1ActivityList()

        assert len(result) == 1
        assert result[0][0] == ""


class TestGetX1DeviceList:
    """Tests for getX1DeviceList() dynamic list callback."""

    def test_returns_devices_from_transport(self, plugin):
        """Returns menu items from X1 transport devices."""
        transport = MagicMock()
        transport.devices = {
            10: {"name": "TV"},
            20: {"name": "Receiver"},
        }
        plugin._x1_transport = transport

        result = plugin.getX1DeviceList()

        assert (str(10), "TV") in result
        assert (str(20), "Receiver") in result

    def test_returns_placeholder_when_no_transport(self, plugin):
        """Returns placeholder when no X1 transport."""
        plugin._x1_transport = None

        result = plugin.getX1DeviceList()

        assert len(result) == 1
        assert result[0][0] == ""

    def test_returns_placeholder_when_no_devices(self, plugin):
        """Returns placeholder when transport has no devices."""
        transport = MagicMock()
        transport.devices = {}
        plugin._x1_transport = transport

        result = plugin.getX1DeviceList()

        assert len(result) == 1
        assert result[0][0] == ""


class TestGetX1CommandList:
    """Tests for getX1CommandList() dynamic list callback."""

    def test_returns_commands_for_selected_device(self, plugin):
        """Returns commands filtered by targetDeviceId from valuesDict."""
        transport = MagicMock()
        transport.commands = {
            10: [
                {"command_id": 1, "label": "Power"},
                {"command_id": 2, "label": "Volume Up"},
            ],
        }
        plugin._x1_transport = transport

        result = plugin.getX1CommandList(
            valuesDict={"targetDeviceId": "10"},
        )

        assert ("1", "Power") in result
        assert ("2", "Volume Up") in result

    def test_returns_placeholder_when_no_device_selected(self, plugin):
        """Returns placeholder when valuesDict is empty."""
        plugin._x1_transport = MagicMock()

        result = plugin.getX1CommandList(valuesDict=None)

        assert len(result) == 1
        assert result[0][0] == ""

    def test_returns_placeholder_when_device_has_no_commands(self, plugin):
        """Returns placeholder when the device has no commands."""
        transport = MagicMock()
        transport.commands = {}
        plugin._x1_transport = transport

        result = plugin.getX1CommandList(
            valuesDict={"targetDeviceId": "99"},
        )

        assert len(result) == 1
        assert result[0][0] == ""

    def test_fallback_label_when_label_missing(self, plugin):
        """Uses 'Command N' label when label key is missing."""
        transport = MagicMock()
        transport.commands = {
            10: [{"command_id": 42}],
        }
        plugin._x1_transport = transport

        result = plugin.getX1CommandList(
            valuesDict={"targetDeviceId": "10"},
        )

        assert ("42", "Command 42") in result

    def test_returns_placeholder_when_no_transport(self, plugin):
        """Returns placeholder when no X1 transport."""
        plugin._x1_transport = None

        result = plugin.getX1CommandList(valuesDict={"targetDeviceId": "10"})

        assert len(result) == 1
        assert result[0][0] == ""


class TestOnX1ConnectionChange:
    """Tests for _on_x1_connection_change() connection callback."""

    def test_updates_hub_state_on_connected(self, plugin):
        """Hub device state is updated when X1 reports connected."""
        hub_dev = MockIndigoDevice(
            200, device_type_id="sofabatonX1Hub",
            states={"connectionStatus": "disconnected"},
        )
        plugin._x1_hub_dev_id = 200

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.__getitem__ = lambda self, k: hub_dev
            mock_indigo.kStateImageSel.SensorOn = "SensorOn"
            mock_indigo.kStateImageSel.SensorOff = "SensorOff"

            plugin._on_x1_connection_change("connected")

        assert hub_dev.states["connectionStatus"] == "connected"
        assert hub_dev._state_image == "SensorOn"

    def test_updates_hub_state_on_disconnected(self, plugin):
        """Hub device state is updated when X1 reports disconnected."""
        hub_dev = MockIndigoDevice(
            200, device_type_id="sofabatonX1Hub",
            states={"connectionStatus": "connected"},
        )
        plugin._x1_hub_dev_id = 200

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.__getitem__ = lambda self, k: hub_dev
            mock_indigo.kStateImageSel.SensorOn = "SensorOn"
            mock_indigo.kStateImageSel.SensorOff = "SensorOff"

            plugin._on_x1_connection_change("disconnected")

        assert hub_dev.states["connectionStatus"] == "disconnected"
        assert hub_dev._state_image == "SensorOff"

    def test_no_error_when_no_hub_device(self, plugin):
        """No error raised when _x1_hub_dev_id is None."""
        plugin._x1_hub_dev_id = None
        # Should not raise
        plugin._on_x1_connection_change("connected")

    def test_logs_connection_status(self, plugin, mock_logger):
        """Connection change is logged."""
        plugin._x1_hub_dev_id = None
        plugin._on_x1_connection_change("connected")

        mock_logger.info.assert_called()
        assert "connected" in mock_logger.info.call_args[0][0].lower()


class TestSendActivityCommand:
    """Tests for _send_activity_command() transport routing."""

    def test_routes_to_x1_transport_on(self, plugin):
        """x1 transport type routes activate to X1 transport."""
        transport = MagicMock()
        transport.is_connected.return_value = True
        transport.activate.return_value = True
        plugin._x1_transport = transport

        result = plugin._send_activity_command(10, "on", "x1")

        assert result is True
        transport.activate.assert_called_once_with(10)

    def test_routes_to_x1_transport_off(self, plugin):
        """x1 transport type routes deactivate to X1 transport."""
        transport = MagicMock()
        transport.is_connected.return_value = True
        transport.deactivate.return_value = True
        plugin._x1_transport = transport

        result = plugin._send_activity_command(10, "off", "x1")

        assert result is True
        transport.deactivate.assert_called_once_with(10)

    def test_returns_false_when_x1_not_connected(self, plugin):
        """Returns False when X1 transport is not connected."""
        transport = MagicMock()
        transport.is_connected.return_value = False
        plugin._x1_transport = transport

        result = plugin._send_activity_command(10, "on", "x1")

        assert result is False

    def test_returns_false_when_x1_transport_none(self, plugin):
        """Returns False when X1 transport is None."""
        plugin._x1_transport = None

        result = plugin._send_activity_command(10, "on", "x1")

        assert result is False

    def test_routes_to_mqtt_for_mqtt_type(self, plugin):
        """mqtt transport type routes to _send_activity_control."""
        plugin._send_activity_control = MagicMock(return_value=True)

        result = plugin._send_activity_command(10, "on", "mqtt")

        assert result is True
        plugin._send_activity_control.assert_called_once_with(10, "on")
