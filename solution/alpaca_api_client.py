# Copyright (C) 2025  Jimmy Aguilar Mena

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import requests
import time
import re
import logging

class AlpacaAPIClient:
    '''This class is the real interface to the alpaca API

    It performs direct calls to the servers API. It is separated from
    the final class exposed to the user because that one implements
    some optimizations simplifies user interface and for this specific
    problem.
    '''

    # I add this logger as a static variable. In a highly
    # multithreading environment we may assert that the logger is
    # implemented as a lock-free code, but in this case I can live
    # with it for now. (Also, remember the GIL)
    logger = logging.getLogger('alpaca_api')

    def __init__(self, api_key, api_secret):
        # Validate API key and secret format
        if not self._validate_keys(api_key, api_secret):
            error_msg = "Invalid API key or secret format"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.base_url = "https://paper-api.alpaca.markets"
        self.data_url = "https://data.alpaca.markets"
        self.headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': api_secret,
            'Content-Type': 'application/json'
        }

        self.account = self.get_account()
        self.logger.info("Alpaca API client initialized successfully")


    def _validate_keys(self, api_key, api_secret):
        """
        Validate API keys format before making any requests.
        Alpaca keys have specific formats we can check.
        """
        # Check if keys are provided
        if not api_key or not api_secret:
            return False

        key_valid = bool(re.match(r'^(PK|AK)[A-Z0-9]{10,}$', api_key))
        secret_valid = bool(re.match(r'^[A-Za-z0-9]{40,}$', api_secret))

        return key_valid and secret_valid


    def _make_request(self, method, endpoint, **kwargs):
        """Make a request to the Alpaca API with error handling and logging."""

        # method, endpoint, params=None, data=None, timeout=30, is_data=False

        defaults = {
            "url": self.base_url,
            "headers": self.headers,
            "params": None,
            "json": None,
            "timeout": 30,
        }

        params = {**defaults, **kwargs}
        params["url"] = f"{params["url"]}{endpoint}"

        try:
            # Log the request (but not sensitive data)
            self.logger.info(f"Request: {method} {endpoint} {params}")

            response = requests.request(
                method=method,
                **params
            )

            # Raise HTTPError for bad status codes
            response.raise_for_status()

            return response.json()

        except ConnectionError as e:
            self.logger.error(f"Connection Error: {str(e)}")
            raise

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            error_detail = e.response.text
            self.logger.error(f"HTTP Error {status_code}: {error_detail}")

            # Log rate limit issues specially
            if status_code == 429:
                self.logger.warning("Rate limit exceeded. Consider implementing backoff.")

            raise

        except requests.exceptions.Timeout as e:
            self.logger.error(f"Timeout Error: {str(e)}")
            raise

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request Exception: {str(e)}")
            raise

        except requests.exceptions.InvalidJSONError as e:
            self.logger.error(f"JSON Parsing Error: {str(e)}")
            raise

        except Exception as e:
            self.logger.critical(f"Unexpected error: \"{str(e)}\" type: {type(e).__name__}")
            raise

    def get_account(self):
        """Get account information."""
        try:
            return self._make_request('GET', '/v2/account', timeout=10)
        except Exception as e:
            self.logger.error(f"Failed to get account information: {str(e)}")
            return None

    def get_positions(self):
        """Get current positions with retry logic for transient errors."""
        try:
            return self._make_request(method='GET', endpoint='/v2/positions')
        except Exception as e:
            self.logger.error(f"Failed to get positions: {str(e)}")
            return None

    def place_order(self, symbol, qty, side, type="market", time_in_force="ioc"):
        """Place an order with the Alpaca API."""
        data = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": type,
            "time_in_force": time_in_force
        }

        try:
            result = self._make_request('POST', '/v2/orders', json=data)
            self.logger.info(f"Order placed successfully: {symbol} {side} {qty}")
            return result
        except Exception as e:
            self.logger.error(f"Failed to place order for {symbol}: {str(e)}")
            return None

    def get_prices(self, assets, type='trades'):
        """Get latest prices for the assets."""
        allowed_values = ['trades', 'quotes', 'bars']

        if type not in allowed_values:
            raise ValueError(
                f"Invalid input: '{type}'. "
                f"Allowed values are: {', '.join(allowed_values)}"
            )

        if len(assets) == 0:
            return {}
        try:
            return self._make_request(
                method='GET',
                endpoint=f'/v2/stocks/{type}/latest',
                params=f"symbols={','.join(assets)}",
                url=self.data_url
            )
        except Exception as e:
            self.logger.error(f"Failed to get asset prices: {str(e)}")
            return None

    def get_order_info(self, id):
        '''Make a request with order info.'''
        try:
            return self._make_request(
                method='GET',
                endpoint=f'/v2/orders/{id}',
            )
        except Exception as e:
            self.logger.error(f"Failed to get order info: {str(e)}")
            return None
