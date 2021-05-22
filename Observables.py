import datetime
import logging
import rx
import rx.operators as ops
import typing

from rxpy_backpressure import BackPressure

class PrintingObserverSubscriber(rx.core.typing.Observer):
    def __init__(self, report_no_output: bool) -> None:
        super().__init__()
        self.report_no_output = report_no_output

    def on_next(self, item: typing.Any) -> None:
        self.report_no_output = False
        print(item)

    def on_error(self, ex: Exception) -> None:
        self.report_no_output = False
        print(ex)

    def on_completed(self) -> None:
        if self.report_no_output:
            print("No items to show.")

class TimestampedPrintingObserverSubscriber(PrintingObserverSubscriber):
    def __init__(self, report_no_output: bool) -> None:
        super().__init__(report_no_output)

    def on_next(self, item: typing.Any) -> None:
        super().on_next(f"{datetime.datetime.now()}: {item}")

class CollectingObserverSubscriber(rx.core.typing.Observer):
    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.collected: typing.List[typing.Any] = []

    def on_next(self, item: typing.Any) -> None:
        self.collected += [item]

    def on_error(self, ex: Exception) -> None:
        self.logger.error(f"Received error: {ex}")

    def on_completed(self) -> None:
        pass

class CaptureFirstItem:
    def __init__(self):
        self.captured: typing.Any = None
        self.has_captured: bool = False

    def capture_if_first(self, item: typing.Any) -> typing.Any:
        if not self.has_captured:
            self.captured = item
            self.has_captured = True

        return item

class FunctionObserver(rx.core.typing.Observer):
    def __init__(self,
                 on_next: typing.Callable[[typing.Any], None],
                 on_error: typing.Callable[[Exception], None] = lambda _: None,
                 on_completed: typing.Callable[[], None] = lambda: None):
        self._on_next = on_next
        self._on_error = on_error
        self._on_completed = on_completed

    def on_next(self, value: typing.Any) -> None:
        self._on_next(value)

    def on_error(self, error: Exception) -> None:
        self._on_error(error)

    def on_completed(self) -> None:
        self._on_completed()

def create_backpressure_skipping_observer(on_next: typing.Callable[[typing.Any], None], on_error: typing.Callable[[Exception], None] = lambda _: None, on_completed: typing.Callable[[], None] = lambda: None) -> rx.core.typing.Observer:
    observer = FunctionObserver(on_next=on_next, on_error=on_error, on_completed=on_completed)
    return BackPressure.LATEST(observer)


def debug_print_item(title: str) -> typing.Callable[[typing.Any], typing.Any]:
    def _debug_print_item(item: typing.Any) -> typing.Any:
        print(title, item)
        return item

    return ops.map(_debug_print_item)

def log_subscription_error(error: Exception) -> None:
    logging.error(f"Observable subscription error: {error}")

def observable_pipeline_error_reporter(ex, _):
    logging.error(f"Intercepted error in observable pipeline: {ex}")
    raise ex

TEventDatum = typing.TypeVar('TEventDatum')


class EventSource(rx.subject.Subject, typing.Generic[TEventDatum]):
    def __init__(self) -> None:
        super().__init__()
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def on_next(self, event: TEventDatum) -> None:
        super().on_next(event)

    def on_error(self, ex: Exception) -> None:
        super().on_error(ex)

    def on_completed(self) -> None:
        super().on_completed()

    def publish(self, event: TEventDatum) -> None:
        try:
            self.on_next(event)
        except Exception as exception:
            self.logger.warning(f"Failed to publish event '{event}' - {exception}")

    def dispose(self) -> None:
        super().dispose()

if __name__ == "__main__":
    rx.from_([1, 2, 3, 4, 5]).subscribe(PrintingObserverSubscriber(False))
    rx.from_([1, 2, 3, 4, 5]).pipe(
        ops.filter(lambda item: (item % 2) == 0),
    ).subscribe(PrintingObserverSubscriber(False))

    collector = CollectingObserverSubscriber()
    rx.from_(["a", "b", "c"]).subscribe(collector)
    print(collector.collected)

    rx.from_([1, 2, 3, 4, 5]).pipe(
        ops.map(debug_print_item("Before even check:")),
        ops.filter(lambda item: (item % 2) == 0),
        ops.map(debug_print_item("After even check:")),
    ).subscribe(PrintingObserverSubscriber(True))

