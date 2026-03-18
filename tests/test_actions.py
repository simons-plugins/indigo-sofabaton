"""Tests for device control actions and custom action callbacks."""
from unittest.mock import patch, MagicMock, PropertyMock

from conftest import MockIndigoDevice
from plugin import KEY_IDS


class MockAction:
    """Mock Indigo action object."""

    def __init__(self, device_action=None, props=None):
        self.deviceAction = device_action
        self.props = props or {}


class TestActionControlDevice:
    """Tests for actionControlDevice — turn on/off/toggle activities."""

    def test_turn_on_sends_activity_on(self, plugin, activity_device):
        action = MockAction(device_action=1)  # TurnOn
        plugin._send_activity_control = MagicMock(return_value=True)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4
            mock_indigo.kStateImageSel.PowerOn = "PowerOn"
            mock_indigo.kStateImageSel.PowerOff = "PowerOff"
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100)

            plugin.actionControlDevice(action, activity_device)

        plugin._send_activity_control.assert_called_once_with(1, "on")

    def test_turn_off_sends_activity_off(self, plugin, activity_device):
        action = MockAction(device_action=2)  # TurnOff
        plugin._send_activity_control = MagicMock(return_value=True)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4
            mock_indigo.kStateImageSel.PowerOff = "PowerOff"
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100)

            plugin.actionControlDevice(action, activity_device)

        plugin._send_activity_control.assert_called_once_with(1, "off")

    def test_turn_on_updates_device_state(self, plugin, activity_device):
        action = MockAction(device_action=1)  # TurnOn
        plugin._send_activity_control = MagicMock(return_value=True)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4
            mock_indigo.kStateImageSel.PowerOn = "PowerOn"
            mock_indigo.kStateImageSel.PowerOff = "PowerOff"
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100)

            plugin.actionControlDevice(action, activity_device)

        assert activity_device.onState is True

    def test_turn_on_failure_does_not_update_state(self, plugin, activity_device):
        action = MockAction(device_action=1)  # TurnOn
        plugin._send_activity_control = MagicMock(return_value=False)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4

            plugin.actionControlDevice(action, activity_device)

        assert activity_device.onState is False

    def test_toggle_from_off_turns_on(self, plugin, activity_device):
        activity_device.onState = False
        action = MockAction(device_action=3)  # Toggle
        plugin._send_activity_control = MagicMock(return_value=True)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4
            mock_indigo.kStateImageSel.PowerOn = "PowerOn"
            mock_indigo.kStateImageSel.PowerOff = "PowerOff"
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100)

            plugin.actionControlDevice(action, activity_device)

        plugin._send_activity_control.assert_called_once_with(1, "on")

    def test_toggle_from_on_turns_off(self, plugin, activity_device):
        activity_device.onState = True
        action = MockAction(device_action=3)  # Toggle
        plugin._send_activity_control = MagicMock(return_value=True)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4
            mock_indigo.kStateImageSel.PowerOn = "PowerOn"
            mock_indigo.kStateImageSel.PowerOff = "PowerOff"
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100)

            plugin.actionControlDevice(action, activity_device)

        plugin._send_activity_control.assert_called_once_with(1, "off")

    def test_ignores_non_activity_device(self, plugin):
        hub_dev = MockIndigoDevice(100, device_type_id="sofabatonHub")
        action = MockAction(device_action=1)
        plugin._send_activity_control = MagicMock()

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            plugin.actionControlDevice(action, hub_dev)

        plugin._send_activity_control.assert_not_called()

    def test_request_status_refreshes(self, plugin, activity_device):
        action = MockAction(device_action=4)  # RequestStatus
        plugin._request_activity_list = MagicMock()

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.kDeviceAction.TurnOn = 1
            mock_indigo.kDeviceAction.TurnOff = 2
            mock_indigo.kDeviceAction.Toggle = 3
            mock_indigo.kDeviceAction.RequestStatus = 4

            plugin.actionControlDevice(action, activity_device)

        plugin._request_activity_list.assert_called_once()


class TestSendKeyPress:
    """Tests for sendKeyPress action callback."""

    def test_sends_correct_key(self, plugin, activity_device):
        action = MockAction(props={"keyName": "volume_up"})
        plugin._send_key_control = MagicMock(return_value=True)

        plugin.sendKeyPress(action, activity_device)

        plugin._send_key_control.assert_called_once_with(1, 182)

    def test_unknown_key_logs_error(self, plugin, activity_device):
        action = MockAction(props={"keyName": "nonexistent"})
        plugin._send_key_control = MagicMock()

        plugin.sendKeyPress(action, activity_device)

        plugin._send_key_control.assert_not_called()
        plugin.logger.error.assert_called()


class TestSendKeyToCurrentActivity:
    """Tests for sendKeyToCurrentActivity action callback."""

    def test_sends_to_active_activity(self, plugin):
        plugin._activities = {
            1: {"name": "Watch TV", "state": "off"},
            2: {"name": "Music", "state": "on"},
        }
        action = MockAction(props={"keyName": "ok"})
        plugin._send_key_control = MagicMock(return_value=True)

        plugin.sendKeyToCurrentActivity(action)

        plugin._send_key_control.assert_called_once_with(2, KEY_IDS["ok"])

    def test_error_when_no_active_activity(self, plugin):
        plugin._activities = {
            1: {"name": "Watch TV", "state": "off"},
        }
        action = MockAction(props={"keyName": "ok"})
        plugin._send_key_control = MagicMock()

        plugin.sendKeyToCurrentActivity(action)

        plugin._send_key_control.assert_not_called()
        plugin.logger.error.assert_called_with("No activity is currently active")


class TestSendMacroKey:
    """Tests for sendMacroKey action callback."""

    def test_sends_macro_key(self, plugin, activity_device):
        action = MockAction(props={"macroKeyId": "100"})
        plugin._send_macro_key = MagicMock(return_value=True)

        plugin.sendMacroKey(action, activity_device)

        plugin._send_macro_key.assert_called_once_with(1, 100)

    def test_invalid_key_id_logs_error(self, plugin, activity_device):
        action = MockAction(props={"macroKeyId": "abc"})
        plugin._send_macro_key = MagicMock()

        plugin.sendMacroKey(action, activity_device)

        plugin._send_macro_key.assert_not_called()
        plugin.logger.error.assert_called()


class TestSendFavoriteKey:
    """Tests for sendFavoriteKey action callback."""

    def test_sends_favorite_key(self, plugin, activity_device):
        action = MockAction(props={"favoriteKeyId": "200", "favoriteDeviceId": "5"})
        plugin._send_favorite_key = MagicMock(return_value=True)

        plugin.sendFavoriteKey(action, activity_device)

        plugin._send_favorite_key.assert_called_once_with(5, 200)

    def test_invalid_ids_logs_error(self, plugin, activity_device):
        action = MockAction(props={"favoriteKeyId": "abc", "favoriteDeviceId": "xyz"})
        plugin._send_favorite_key = MagicMock()

        plugin.sendFavoriteKey(action, activity_device)

        plugin._send_favorite_key.assert_not_called()
        plugin.logger.error.assert_called()
