import unittest
from unittest.mock import patch, MagicMock
import os
import alpaca_api_client as aaclient
from alpaca_api_wrapper import AlpacaAPIWrapper  # Assuming the module is named this way

class TestAlpacaAPIWrapper(unittest.TestCase):

    @patch("alpaca_api_client.AlpacaAPIClient")
    def setUp(self, mock_client):
        # Mock the AlpacaAPIClient instance
        self.mock_client_instance = mock_client.return_value
        self.mock_client_instance.get_positions.return_value = [
            {"symbol": "AAPL", "qty_available": "10", "market_value": "1500", "current_price": "150"}
        ]
        self.mock_client_instance.get_prices.return_value = {"trades": {"AAPL": {"p": 150.0}}}
        self.mock_client_instance.get_account.return_value = {"cash": "10000"}

        self.wrapper = AlpacaAPIWrapper("PKTEST123456", "abcdefghijklmnopqrstuvwxyz1234567890")

    def test_initialization(self):
        self.assertEqual(self.wrapper.positions, {'AAPL': {'qty': 10.0, 'value': 1500.0}})
        self.assertEqual(self.wrapper.last_prices, {'AAPL': 150.0})
        self.assertIn("AAPL", self.wrapper.assets)
        self.assertEqual(self.wrapper.cash, 10000)

    def test_add_asset(self):
        self.wrapper.add_asset("MSFT")
        self.assertIn("MSFT", self.wrapper.assets)

    @patch.object(AlpacaAPIWrapper, "update_prices")
    def test_update_prices(self, mock_update_prices):
        mock_update_prices.return_value = None
        self.wrapper.update_prices()
        self.assertIn("AAPL", self.wrapper.last_prices)

    @patch.object(AlpacaAPIWrapper, "update_positions")
    def test_update_positions(self, mock_update_positions):
        mock_update_positions.return_value = None
        self.wrapper.update_positions()
        self.assertIn("AAPL", self.wrapper.positions)

    @patch.object(AlpacaAPIWrapper, "update_cash")
    def test_update_cash(self, mock_update_cash):
        mock_update_cash.return_value = None
        self.wrapper.update_cash()
        self.assertEqual(self.wrapper.client.get_account().get("cash"), "10000")

if __name__ == "__main__":
    unittest.main()
