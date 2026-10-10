import os
import sys

from loguru import logger
from tqdm import tqdm

tqdm_stream = sys.stderr
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(PROJECT_ROOT, "chaoxing.log")


def tqdm_sink(msg):
    tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()


logger.remove()
logger.add(tqdm_sink, colorize=True, enqueue=True)
logger.add(LOG_FILE, rotation="10 MB", level="TRACE")
