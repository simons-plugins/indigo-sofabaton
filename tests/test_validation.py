"""Tests for config validation — plugin prefs and device config."""
from plugin import KEY_IDS


class TestValidatePrefsConfigUi:
    """Tests for validatePrefsConfigUi."""

    def test_valid_config(self, plugin):
        values = {
            "mqttBrokerHost": "192.168.0.2",
            "mqttBrokerPort": "1883",
            "hubMac": "206EF1241808",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is True

    def test_empty_host_fails(self, plugin):
        values = {
            "mqttBrokerHost": "",
            "mqttBrokerPort": "1883",
            "hubMac": "206EF1241808",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is False
        assert "mqttBrokerHost" in result[2]

    def test_invalid_port_fails(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "abc",
            "hubMac": "",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is False
        assert "mqttBrokerPort" in result[2]

    def test_port_out_of_range_fails(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "99999",
            "hubMac": "",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is False
        assert "mqttBrokerPort" in result[2]

    def test_empty_mac_is_allowed(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "1883",
            "hubMac": "",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is True

    def test_short_mac_fails(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "1883",
            "hubMac": "AABB",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is False
        assert "hubMac" in result[2]

    def test_non_hex_mac_fails(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "1883",
            "hubMac": "GGGGGGGGGGGG",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is False
        assert "hubMac" in result[2]

    def test_mac_with_colons_accepted(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "1883",
            "hubMac": "20:6E:F1:24:18:08",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is True

    def test_mac_with_dashes_accepted(self, plugin):
        values = {
            "mqttBrokerHost": "localhost",
            "mqttBrokerPort": "1883",
            "hubMac": "20-6E-F1-24-18-08",
        }
        result = plugin.validatePrefsConfigUi(values)
        assert result[0] is True


class TestValidateDeviceConfigUi:
    """Tests for validateDeviceConfigUi."""

    def test_valid_hub_mac(self, plugin):
        values = {"macAddress": "206EF1241808"}
        result = plugin.validateDeviceConfigUi(values, "sofabatonHub", 0)
        assert result[0] is True

    def test_empty_hub_mac_fails(self, plugin):
        values = {"macAddress": ""}
        result = plugin.validateDeviceConfigUi(values, "sofabatonHub", 0)
        assert result[0] is False
        assert "macAddress" in result[2]

    def test_short_hub_mac_fails(self, plugin):
        values = {"macAddress": "AABB"}
        result = plugin.validateDeviceConfigUi(values, "sofabatonHub", 0)
        assert result[0] is False

    def test_non_hub_device_skips_mac_validation(self, plugin):
        values = {}
        result = plugin.validateDeviceConfigUi(values, "sofabatonActivity", 0)
        assert result[0] is True


class TestKeyIds:
    """Tests for KEY_IDS constant."""

    def test_has_27_keys(self):
        assert len(KEY_IDS) == 27

    def test_directional_keys(self):
        assert KEY_IDS["up"] == 174
        assert KEY_IDS["down"] == 178
        assert KEY_IDS["left"] == 175
        assert KEY_IDS["right"] == 177
        assert KEY_IDS["ok"] == 176

    def test_volume_keys(self):
        assert KEY_IDS["volume_up"] == 182
        assert KEY_IDS["volume_down"] == 185
        assert KEY_IDS["mute"] == 184

    def test_media_keys(self):
        assert KEY_IDS["play"] == 156
        assert KEY_IDS["pause"] == 188
        assert KEY_IDS["rewind"] == 187
        assert KEY_IDS["fast_forward"] == 189

    def test_color_keys(self):
        assert KEY_IDS["red"] == 190
        assert KEY_IDS["green"] == 191
        assert KEY_IDS["yellow"] == 192
        assert KEY_IDS["blue"] == 193

    def test_all_values_unique(self):
        values = list(KEY_IDS.values())
        assert len(values) == len(set(values))
