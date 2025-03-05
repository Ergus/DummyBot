import unittest
from unittest.mock import patch, MagicMock
from alpaca_api_client import AlpacaAPIClient  # Assuming the module is named this way

class TestAlpacaAPIClient(unittest.TestCase):

    def setUp(self):
        self.api_key = "PKCX4ZFB46VG8WJE46TJ"
        self.api_secret = "mIytMtNrhTpPwOUPL8rLdQf9Hf3MMQuB1pArFV8q"
        self.client = AlpacaAPIClient(self.api_key, self.api_secret)

    def test_alpaca_api_client_initialization(self):
        self.assertEqual(self.client.base_url, "https://paper-api.alpaca.markets")
        self.assertEqual(self.client.headers['APCA-API-KEY-ID'], self.api_key)
        self.assertEqual(self.client.headers['APCA-API-SECRET-KEY'], self.api_secret)

    def test_validate_keys_valid(self):
        self.assertTrue(self.client._validate_keys(self.api_key, self.api_secret))

    def test_validate_keys_invalid(self):
        self.assertFalse(self.client._validate_keys("INVALID", "SHORT"))

    @patch("requests.request")
    def test_get_account_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "account_123"}
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        account = self.client.get_account()
        self.assertEqual(account["id"], "account_123")

    @patch("requests.request")
    def test_get_account_failure(self, mock_request):
        mock_request.side_effect = Exception("API Failure")
        self.assertIsNone(self.client.get_account())

    @patch("requests.request")
    def test_get_positions_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"symbol": "AAPL", "qty": 10}]
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        positions = self.client.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "AAPL")

    @patch("requests.request")
    def test_get_positions_failure(self, mock_request):
        mock_request.side_effect = Exception("API Failure")
        self.assertIsNone(self.client.get_positions())

    @patch("requests.request")
    def test_place_order_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "order_123"}
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        order = self.client.place_order("AAPL", 1, "buy")
        self.assertEqual(order["id"], "order_123")

    @patch("requests.request")
    def test_place_order_failure(self, mock_request):
        mock_request.side_effect = Exception("Order Failed")
        self.assertIsNone(self.client.place_order("AAPL", 1, "buy"))

if __name__ == "__main__":
    unittest.main()
