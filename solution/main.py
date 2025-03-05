import redis
import queue
import os
import logging
import threading
import alpaca_api_wrapper
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='strategy_api.log'
)

signal_queue = queue.Queue()

def redis_reader():
    redis_client = redis.Redis(
        host='redis',
        port=6379,
        decode_responses=True
    )

    logger = logging.getLogger('redis')
    logger.info("Waiting for signals...")

    # Get the latest entry ID or use '0' if none exists
    last_id = '0'

    # TODO: This may be a polling service, so needs reimplementaton to
    # bypass the GIL during reading (with is save)
    # But enable temporarily when calling the put.
    # Maybe the redis API does it internally in the C side, but In my
    # experience it is better not thrust
    while True:
        # Read new messages from the stream
        response = redis_client.xread(
            {'nvda': last_id},
            block=1000
        )

        if response:
            if len(response) > 1:
                logger.warning(f"Received {len(response)} signals")
            # Update last_id and print new messages
            for stream_name, messages in response:
                for message_id, data in messages:
                    last_id = message_id
                    logger.info(f"New signal {data}")
                    signal_queue.put(data)

# ===================================

def pooling(client: alpaca_api_wrapper.AlpacaAPIWrapper):
    logger = logging.getLogger('worker')
    logger.info("Pooling...")

    while True:
        client.update_prices()
        time.sleep(1)


def worker(client: alpaca_api_wrapper.AlpacaAPIWrapper):
    logger = logging.getLogger('worker')
    logger.info("Waiting for signals...")

    while True:
        data = signal_queue.get() # blockingly pop data from the fifo queue

        logger.info(f"Received new signal {data}")

        match data.get("direction"):
            case "b":
                client.manage_buy_signal(data.get("ticker"))
            case "s":
                client.manage_sell_signal(data.get("ticker"))


def bot():

    client = alpaca_api_wrapper.AlpacaAPIWrapper(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY")
    )


    tpooling = threading.Thread(target=pooling, args = (client), name='tPooling')
    tredis = threading.Thread(target=redis_reader, name='tRedis')
    tworker = threading.Thread(target=worker, args = (client), name='tWorker')

    tredis.join()
    tworker.join()
    tpooling.join()

if __name__ == "__main__":
    #main()
    TestFun()
