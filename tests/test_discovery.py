import unittest
from unittest.mock import MagicMock
from custom_components.nexus_mcp.discovery import async_autodiscover_ha_mcp_url

class TestDiscovery(unittest.TestCase):
    def test_autodiscover_direct_port(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {"secret_path": "/test_secret"}
        hass.config_entries.async_entries.return_value = [entry]

        url = async_autodiscover_ha_mcp_url(hass)
        self.assertEqual(url, "http://127.0.0.1:9584/test_secret")

    def test_autodiscover_webhook(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {"webhook_id": "wh_12345"}
        hass.config_entries.async_entries.return_value = [entry]

        url = async_autodiscover_ha_mcp_url(hass)
        self.assertEqual(url, "http://127.0.0.1:8123/api/webhook/wh_12345")

    def test_autodiscover_none_when_not_installed(self):
        hass = MagicMock()
        hass.config_entries.async_entries.return_value = []

        url = async_autodiscover_ha_mcp_url(hass)
        self.assertIsNone(url)

if __name__ == "__main__":
    unittest.main()
