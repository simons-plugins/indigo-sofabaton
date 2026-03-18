"""Tests for MQTT message handling — activity list, state changes, keys, dedup."""
import json
import time
from unittest.mock import patch, MagicMock

from conftest import MockMQTTMessage, MockIndigoDevice


class TestActivityListHandling:
    """Tests for _handle_activity_list."""

    def test_parses_activity_list(self, plugin, activity_list_payload):
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.device.create.return_value = MockIndigoDevice(201, "Test")
            plugin._handle_activity_list(activity_list_payload)

        assert len(plugin._activities) == 3
        assert plugin._activities[1]["name"] == "Watch TV"
        assert plugin._activities[2]["name"] == "Listen to Music"
        assert plugin._activities[3]["name"] == "Play Games"

    def test_preserves_activity_state(self, plugin, activity_list_payload):
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.device.create.return_value = MockIndigoDevice(201, "Test")
            plugin._handle_activity_list(activity_list_payload)

        assert plugin._activities[1]["state"] == "off"
        assert plugin._activities[3]["state"] == "on"

    def test_empty_activity_list(self, plugin):
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            plugin._handle_activity_list({"data": []})

        assert len(plugin._activities) == 0

    def test_replaces_previous_activities(self, plugin):
        # Old activity belongs to the same hub (X2, hub_dev_id=100)
        plugin._activities = {99: {"name": "Old", "state": "on", "_hub_dev_id": 100}}

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.device.create.return_value = MockIndigoDevice(201, "Test")
            plugin._handle_activity_list({
                "data": [{"activity_id": 1, "activity_name": "New", "state": "off"}]
            })

        assert 99 not in plugin._activities
        assert 1 in plugin._activities


class TestActivityStateHandling:
    """Tests for _handle_activity_state."""

    def test_activity_turns_on(self, plugin):
        plugin._activities = {
            1: {"name": "Watch TV", "state": "off"},
            2: {"name": "Music", "state": "off"},
        }
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100, device_type_id="sofabatonHub")
            plugin._handle_activity_state({"activity_id": 1, "state": "on"})

        assert plugin._activities[1]["state"] == "on"
        assert plugin._activities[2]["state"] == "off"

    def test_activity_turns_off(self, plugin):
        plugin._activities = {1: {"name": "Watch TV", "state": "on"}}
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100, device_type_id="sofabatonHub")
            plugin._handle_activity_state({"activity_id": 1, "state": "off"})

        assert plugin._activities[1]["state"] == "off"

    def test_only_one_activity_on_at_a_time(self, plugin):
        plugin._activities = {
            1: {"name": "Watch TV", "state": "on"},
            2: {"name": "Music", "state": "off"},
            3: {"name": "Games", "state": "off"},
        }
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100, device_type_id="sofabatonHub")
            plugin._handle_activity_state({"activity_id": 2, "state": "on"})

        assert plugin._activities[1]["state"] == "off"
        assert plugin._activities[2]["state"] == "on"
        assert plugin._activities[3]["state"] == "off"

    def test_all_off_with_activity_255(self, plugin):
        plugin._activities = {
            1: {"name": "Watch TV", "state": "on"},
            2: {"name": "Music", "state": "off"},
        }
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100, device_type_id="sofabatonHub")
            plugin._handle_activity_state({"activity_id": 255, "state": "off"})

        assert plugin._activities[1]["state"] == "off"
        assert plugin._activities[2]["state"] == "off"

    def test_unknown_activity_requests_refresh(self, plugin):
        plugin._activities = {}
        plugin._request_activity_list = MagicMock()

        plugin._handle_activity_state({"activity_id": 99, "state": "on"})

        plugin._request_activity_list.assert_called_once()
        assert 99 not in plugin._activities


class TestKeysListHandling:
    """Tests for _handle_keys_list."""

    def test_logs_assigned_keys(self, plugin, keys_list_payload):
        plugin._handle_keys_list(keys_list_payload, "assigned")
        plugin.logger.info.assert_any_call(
            "Received 3 assigned keys for activity/device 1"
        )

    def test_logs_macro_keys_with_names(self, plugin, macro_keys_payload):
        plugin._handle_keys_list(macro_keys_payload, "macro")
        plugin.logger.info.assert_any_call(
            "  macro key: id=100, name='Power On Sequence'"
        )

    def test_logs_favorite_keys_with_names(self, plugin, favorites_keys_payload):
        plugin._handle_keys_list(favorites_keys_payload, "favorite")
        plugin.logger.info.assert_any_call(
            "  favorite key: id=200, name='BBC One'"
        )


class TestDeviceListHandling:
    """Tests for _handle_device_list."""

    def test_logs_devices(self, plugin):
        payload = {
            "data": [
                {"device_id": 1, "device_name": "Samsung TV"},
                {"device_id": 2, "device_name": "Sonos"},
            ]
        }
        plugin._handle_device_list(payload)
        plugin.logger.info.assert_any_call("Received 2 devices from hub")
        plugin.logger.info.assert_any_call("  Device: id=1, name='Samsung TV'")


class TestMessageDedup:
    """Tests for message deduplication in _on_message."""

    def test_duplicate_message_ignored(self, plugin):
        mac = plugin.hubMac
        topic = "activity/%s/list" % mac
        payload = {"data": [{"activity_id": 1, "activity_name": "TV", "state": "off"}]}
        msg = MockMQTTMessage(topic, payload)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            # First message processes
            plugin._on_message(None, None, msg)
            assert len(plugin._activities) == 1

            # Reset and send same message again
            plugin._activities = {}
            plugin._on_message(None, None, msg)
            # Should be deduped — activities not repopulated
            assert len(plugin._activities) == 0

    def test_different_message_not_deduped(self, plugin):
        mac = plugin.hubMac
        topic = "activity/%s/list" % mac
        payload1 = {"data": [{"activity_id": 1, "activity_name": "TV", "state": "off"}]}
        payload2 = {"data": [{"activity_id": 1, "activity_name": "TV", "state": "on"}]}

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            plugin._on_message(None, None, MockMQTTMessage(topic, payload1))
            plugin._on_message(None, None, MockMQTTMessage(topic, payload2))
            # Both should process — different payloads
            assert plugin._activities[1]["state"] == "on"

    def test_same_message_after_dedup_window(self, plugin):
        plugin.DEDUP_SECONDS = 0  # Expire immediately
        mac = plugin.hubMac
        topic = "activity/%s/list" % mac
        payload = {"data": [{"activity_id": 1, "activity_name": "TV", "state": "off"}]}
        msg = MockMQTTMessage(topic, payload)

        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            plugin._on_message(None, None, msg)
            # Fake the timestamp to be old
            for k in plugin._recent_messages:
                h, _ = plugin._recent_messages[k]
                plugin._recent_messages[k] = (h, time.time() - 10)

            plugin._activities = {}
            plugin._on_message(None, None, msg)
            assert len(plugin._activities) == 1


class TestMessageRouting:
    """Tests for topic routing in _on_message."""

    def test_routes_activity_list(self, plugin):
        mac = plugin.hubMac
        msg = MockMQTTMessage(
            "activity/%s/list" % mac,
            {"data": [{"activity_id": 1, "activity_name": "TV", "state": "off"}]}
        )
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            plugin._on_message(None, None, msg)
        assert 1 in plugin._activities

    def test_routes_activity_state(self, plugin):
        mac = plugin.hubMac
        plugin._activities = {1: {"name": "TV", "state": "off"}}
        msg = MockMQTTMessage(
            "activity/%s/activity_control_up" % mac,
            {"activity_id": 1, "state": "on"}
        )
        with patch("plugin.indigo") as mock_indigo:
            mock_indigo.devices.iter.return_value = []
            mock_indigo.devices.__getitem__ = lambda self, k: MockIndigoDevice(100, device_type_id="sofabatonHub")
            plugin._on_message(None, None, msg)
        assert plugin._activities[1]["state"] == "on"

    def test_routes_device_list(self, plugin):
        mac = plugin.hubMac
        msg = MockMQTTMessage(
            "device/%s/list" % mac,
            {"data": [{"device_id": 1, "device_name": "TV"}]}
        )
        plugin._on_message(None, None, msg)
        plugin.logger.info.assert_any_call("Received 1 devices from hub")

    def test_ignores_unknown_topic(self, plugin):
        msg = MockMQTTMessage("unknown/topic", {"data": "test"})
        plugin._on_message(None, None, msg)
        # Should not error
        plugin.logger.error.assert_not_called()

    def test_handles_malformed_json(self, plugin):
        mac = plugin.hubMac
        msg = MockMQTTMessage("activity/%s/list" % mac, "not json{{{")
        plugin._on_message(None, None, msg)
        plugin.logger.error.assert_called()
