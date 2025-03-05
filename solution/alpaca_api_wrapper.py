import os
import alpaca_api_client as aaclient

from threading import Lock

class AlpacaAPIWrapper:
    """This is a wrapper class to reduce api calls.

    The exposed functions will be effective wrappers to the API call
    functions, but in some cases it adds memoization while precompute
    or use stored values.

    """

    def __init__(self, api_key, api_secret):
        self.client = aaclient.AlpacaAPIClient(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY")
        )
        self.positions = {}
        self.last_prices = {}
        self.assets = set()
        self.cash = 0
        self.lock_price = Lock()

        self.add_asset("AAPL")
        self.update_positions()
        self.update_prices()
        self.update_cash()

    def __str__(self):
        return f"Positions: {self.positions}\n" \
            f"LastPrices: {self.last_prices}\n" \
            f"Assets: {self.assets}\n"\
            f"Cash: {self.cash}"

    def add_asset(self, symbol: str):
        self.assets.add(symbol)

    def update_prices(self, prices = None):

        if prices is None:
            # This won't scale well when using many assets.
            self.assets = self.assets | set([key for key in self.positions.keys()])
            prices = self.client.get_prices(self.assets).get("trades")

        with self.lock_price:
            self.last_prices = {key: values.get("p") for key, values in prices.items()}


    def update_positions(self, positions = None):

        if positions is None:
            positions = self.client.get_positions()

        for position in positions:
            key = position["symbol"]
            self.positions[key] = {
                "qty": float(position.get("qty_available")),
                "value": float(position.get("market_value"))
            }

            self.last_prices[key] = float(position["current_price"])

    def update_cash(self):
        self.cash = float(self.client.get_account().get("cash"))

    def manage_buy_signal(self, ticker):
        price: float = self.last_prices.get()
        qty = self.cash / price;

        self.client.place_order(ticker, qty, "buy")

        self.cash -= qty * price


    def manage_sell_signal(self, ticker):
        self.lock_price.acquire()
        position = self.positions.get(ticker)
        qty = position.get("qty") if position else 0
        self.lock_price.release()

        if qty > 0:
            self.client.place_order(ticker, qty, "sell")
