import logging
import typing

from contextlib import contextmanager

class Retrier:
    def __init__(self, func: typing.Callable, retries: int) -> None:
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.func: typing.Callable = func
        self.retries: int = retries

    def run(self, *args):
        captured_exception: Exception = None
        for counter in range(self.retries):
            try:
                return self.func(*args)
            except Exception as exception:
                self.logger.info(f"Retriable call failed [{counter}] with error '{exception}'. Retrying...")
                captured_exception = exception

        raise captured_exception

@contextmanager
def retry_context(func: typing.Callable, retries: int = 3) -> typing.Iterator[Retrier]:
    yield Retrier(func, retries)

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    def _raiser(value):
        # All this does is raise an exception
        raise Exception(f"This is a test: {value}")

    # NOTE! This will fail by design, with the exception message:
    # "Exception: This is a test: ignored parameter"
    with retry_context(_raiser, 5) as retrier:
        response = retrier.run("ignored parameter")