import json
import logging
import os.path

from solana.account import Account
from solana.publickey import PublicKey


_DEFAULT_WALLET_FILENAME: str = "id.json"


class Wallet:
    def __init__(self, secret_key):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.secret_key = secret_key[0:32]
        self.account = Account(self.secret_key)

    @property
    def address(self) -> PublicKey:
        return self.account.public_key()

    def save(self, filename: str, overwrite: bool = False) -> None:
        if os.path.isfile(filename) and not overwrite:
            raise Exception(f"Wallet file '{filename}' already exists.")

        with open(filename, "w") as json_file:
            json.dump(list(self.secret_key), json_file)

    @staticmethod
    def load(filename: str = _DEFAULT_WALLET_FILENAME) -> "Wallet":
        if not os.path.isfile(filename):
            logging.error(f"Wallet file '{filename}' is not present.")
            raise Exception(f"Wallet file '{filename}' is not present.")
        else:
            with open(filename) as json_file:
                data = json.load(json_file)
                return Wallet(data)

    @staticmethod
    def create() -> "Wallet":
        new_account = Account()
        new_secret_key = new_account.secret_key()
        return Wallet(new_secret_key)


default_wallet = None
if os.path.isfile(_DEFAULT_WALLET_FILENAME):
     try:
         default_wallet = Wallet.load(_DEFAULT_WALLET_FILENAME)
     except Exception as exception:
         logging.warning(
             f"Failed to load default wallet from file '{_DEFAULT_WALLET_FILENAME}' - exception: {exception}")
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    import os.path

    filename = _DEFAULT_WALLET_FILENAME
    if not os.path.isfile(filename):
        print(f"Wallet file '{filename}' is not present.")
    else:
        wallet = Wallet.load(filename)
        print("Wallet address:", wallet.address)