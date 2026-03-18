"""Tests for MQTT publishing — activity control, key presses, topics."""
import json
from unittest.mock import patch, MagicMock

from plugin import KEY_IDS


class TestPublish:
    """Tests for _publish method."""

    def test_publish_sends_json(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._publish("test/topic", {"data": "hello"})

        plugin._mqtt.publish.assert_called_once_with(
            "test/topic", '{"data": "hello"}'
        )

    def test_publish_returns_true_on_success(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        assert plugin._publish("test/topic", {"data": "hello"}) is True

    def test_publish_returns_false_when_disconnected(self, plugin):
        plugin._mqtt_connected = False

        result = plugin._publish("test/topic", {"data": "hello"})

        assert result is False
        plugin.logger.error.assert_called_with("Not connected to MQTT broker")

    def test_publish_returns_false_on_exception(self, plugin):
        plugin._mqtt.publish.side_effect = Exception("publish failed")

        result = plugin._publish("test/topic", {"data": "hello"})

        assert result is False

    def test_publish_logs_when_logMqtt_enabled(self, plugin):
        plugin.logMqtt = True
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._publish("test/topic", {"data": "hello"})

        plugin.logger.debug.assert_called()


class TestActivityControl:
    """Tests for _send_activity_control."""

    def test_sends_activity_on(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_activity_control(1, "on")

        topic = "activity/206EF1241808/activity_control_down"
        expected = json.dumps({"data": {"activity_id": 1, "state": "on"}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)

    def test_sends_activity_off(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_activity_control(1, "off")

        topic = "activity/206EF1241808/activity_control_down"
        expected = json.dumps({"data": {"activity_id": 1, "state": "off"}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)

    def test_stop_all_uses_activity_255(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_activity_control(255, "off")

        topic = "activity/206EF1241808/activity_control_down"
        expected = json.dumps({"data": {"activity_id": 255, "state": "off"}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)


class TestKeyControl:
    """Tests for _send_key_control."""

    def test_sends_key_press(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_key_control(1, 174)

        topic = "activity/206EF1241808/keys_control"
        expected = json.dumps({"data": {"activity_id": 1, "key_id": 174}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)

    def test_sends_volume_up(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_key_control(1, KEY_IDS["volume_up"])

        topic = "activity/206EF1241808/keys_control"
        expected = json.dumps({"data": {"activity_id": 1, "key_id": 182}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)


class TestMacroKeyControl:
    """Tests for _send_macro_key."""

    def test_sends_macro_key(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_macro_key(1, 100)

        topic = "activity/206EF1241808/macro_keys_control"
        expected = json.dumps({"data": {"activity_id": 1, "key_id": 100}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)


class TestFavoriteKeyControl:
    """Tests for _send_favorite_key — device_id goes in activity_id field."""

    def test_sends_favorite_key_with_device_id_quirk(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_favorite_key(device_id=5, key_id=200)

        topic = "activity/206EF1241808/favorites_keys_control"
        # Firmware quirk: device_id goes in activity_id field
        expected = json.dumps({"data": {"activity_id": 5, "key_id": 200}})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)


class TestRequestActivityList:
    """Tests for _request_activity_list."""

    def test_publishes_to_list_request_topic(self, plugin):
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._request_activity_list()

        topic = "activity/206EF1241808/list_request"
        expected = json.dumps({"data": "activity_list"})
        plugin._mqtt.publish.assert_called_once_with(topic, expected)


class TestTopicFormat:
    """Tests for MQTT topic formatting with hub MAC."""

    def test_topics_use_hub_mac(self, plugin):
        plugin.hubMac = "AABBCCDDEEFF"
        result_mock = MagicMock()
        plugin._mqtt.publish.return_value = result_mock

        plugin._send_activity_control(1, "on")

        topic = plugin._mqtt.publish.call_args[0][0]
        assert "AABBCCDDEEFF" in topic

    def test_subscribe_topics(self, plugin):
        plugin.hubMac = "AABBCCDDEEFF"
        plugin._mqtt = MagicMock()

        plugin._subscribe_all()

        subscribed_topics = [call[0][0] for call in plugin._mqtt.subscribe.call_args_list]
        assert "activity/AABBCCDDEEFF/list" in subscribed_topics
        assert "activity/AABBCCDDEEFF/activity_control_up" in subscribed_topics
        assert "activity/AABBCCDDEEFF/keys_list" in subscribed_topics
        assert "activity/AABBCCDDEEFF/macro_keys_list" in subscribed_topics
        assert "activity/AABBCCDDEEFF/favorites_keys_list" in subscribed_topics
        assert "device/AABBCCDDEEFF/list" in subscribed_topics
        assert "device/AABBCCDDEEFF/keys_list" in subscribed_topics
