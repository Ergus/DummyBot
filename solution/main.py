import redis
import queue
import os
import logging
import alpaca_api_wrapper
import time
from concurrent.futures import ThreadPoolExecutor

from typing import Final

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='strategy_api.log'
)

signal_queue = queue.Queue()


def redis_reader():
    '''This is the thread that is constantly blocked waiting for new signals.

    When a signal arrives the information is inserted in the fifo
    signal_queue quickly in order to check for new messages immediately.

    After that a worker will process the signal as soon as
    possible. As there may be many workers, in case multiple signals
    arrive in a short period of time, they may be processed in
    parallel by the workers.
    '''
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
    """Pooling service function

    This pooling service is intended to keep the prices information
    more or less up to date.
    The idea behind is to avoid doing extra requests in the moment we
    receive a signal. When the worker receives a signal it uses the
    prices information that is already cached from the most recent
    request.
    """
    logger = logging.getLogger('worker')
    logger.info("Pooling...")

    pooltime: Final[float] = 1.0

    while True:
        tstart = time.perf_counter()
        client.update_prices()

        if (elapsed := time.perf_counter() - tstart) < pooltime:
            # TODO: use elapsed time to collect some statistics.
            # Use elapsed time for more acurated timer
            time.sleep(pooltime - elapsed)
        else:
            logger.warning(f"Elapsed time to update_prices was: elapsed (< {pooltime})")


def worker(client: alpaca_api_wrapper.AlpacaAPIWrapper):
    '''This is the key strategic function

    This function receives a signal from the queue set by the
    redis_reader. There could be multiple instances of this class.
    The function uses the prices information updated in the last
    pooling loop, needing to take the prices lock very briefly.
    But remember, there is a GIL!!!

    '''

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


def RunBot():
    '''This is the Bot function

    The function uses a thread pool to avoid even the thread creation
    (system call) overhead. The number of threads is limited to 5 not
    because I use 3 threads to update prices.

    '''
    with ThreadPoolExecutor(max_workers=5) as executor:

        client = alpaca_api_wrapper.AlpacaAPIWrapper(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
            ["NVDA"],
            executor
        )

        executor.submit(pooling, client)
        executor.submit(redis_reader)
        executor.submit(worker, client)


if __name__ == "__main__":
    #main()
    RunBot()
