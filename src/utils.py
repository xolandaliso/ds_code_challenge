import time
from src.settings import logger
from contextlib import contextmanager

@contextmanager
def timed(label: str):
    '''
        purpose: simple context manager for measuring & logging execution time.
        usage:
            with timed("some operation"):
                do_something()
    '''
    start = time.perf_counter()
    status = "success"

    try:
        yield
    except Exception:
        status = "failed"
        raise  
    finally:
        elapsed = time.perf_counter() - start
        logger.info(f"{status}: {label} took {elapsed:.3f}s")
