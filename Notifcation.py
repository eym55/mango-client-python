import abc
import logging
import requests
import typing

class NotificationTarget(metaclass=abc.ABCMeta):
    def __init__(self):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def send(self, item: typing.Any) -> None:
        try:
            self.send_notification(item)
        except Exception as exception:
            self.logger.error(f"Error sending {item} - {self} - {exception}")

    @abc.abstractmethod
    def send_notification(self, item: typing.Any) -> None:
        raise NotImplementedError("NotificationTarget.send() is not implemented on the base type.")

    def __repr__(self) -> str:
        return f"{self}"

class TelegramNotificationTarget(NotificationTarget):
    def __init__(self, address):
        super().__init__()
        chat_id, bot_id = address.split("@", 1)
        self.chat_id = chat_id
        self.bot_id = bot_id

    def send_notification(self, item: typing.Any):
        payload = {"disable_notification": True, "chat_id": self.chat_id, "text": str(item)}
        url = f"https://api.telegram.org/bot{self.bot_id}/sendMessage"
        headers = {"Content-Type": "application/json"}
        requests.post(url, json=payload, headers=headers)

    def __str__(self) -> str:
        return f"Telegram chat ID: {self.chat_id}"

class DiscordNotificationTarget(NotificationTarget):
    def __init__(self, address):
        super().__init__()
        self.address = address

    def send_notification(self, item: typing.Any):
        payload = {
            "content": str(item)
        }
        url = self.address
        headers = {"Content-Type": "application/json"}
        requests.post(url, json=payload, headers=headers)

    def __str__(self) -> str:
        return "Discord webhook"

def parse_subscription_target(target):
    protocol, address = target.split(":", 1)

    if protocol == "telegram":
        return TelegramNotificationTarget(address)
    elif protocol == "discord":
        return DiscordNotificationTarget(address)
    else:
        raise Exception(f"Unknown protocol: {protocol}")

class NotificationHandler(logging.StreamHandler):
    def __init__(self, target: NotificationTarget):
        logging.StreamHandler.__init__(self)
        self.target = target

    def emit(self, record):
        message = self.format(record)
        self.target.send_notification(message)

def _notebook_tests():
    test_target = parse_subscription_target("telegram:chat@bot")

    assert(test_target.chat_id == "chat")
    assert(test_target.bot_id == "bot")

_notebook_tests()
del _notebook_tests

if __name__ == "__main__":
    test_target = parse_subscription_target("telegram:chat@bot")
    print(test_target)