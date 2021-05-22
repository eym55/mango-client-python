import decimal
import json
import logging

from solana.publickey import PublicKey

SYSTEM_PROGRAM_ADDRESS = PublicKey("11111111111111111111111111111111")

SOL_DECIMALS = decimal.Decimal(9)

SOL_DECIMAL_DIVISOR = decimal.Decimal(10 ** SOL_DECIMALS)

NUM_TOKENS = 3

NUM_MARKETS = NUM_TOKENS - 1

WARNING_DISCLAIMER_TEXT = """
⚠ WARNING ⚠

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

    🥭 Mango Markets: https://mango.markets
    📄 Documentation: https://docs.mango.markets/
    💬 Discord: https://discord.gg/67jySBhxrg
    🐦 Twitter: https://twitter.com/mangomarkets
    🚧 Github: https://github.com/blockworks-foundation
    📧 Email: mailto:hello@blockworks.foundation
"""

with open("ids.json") as json_file:
    MangoConstants = json.load(json_file)

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    print("System program address:", SYSTEM_PROGRAM_ADDRESS)
    print("SOL decimal divisor:", SOL_DECIMAL_DIVISOR)
    print("Number of tokens:", NUM_TOKENS)
    print("Number of markets:", NUM_MARKETS)
    mango_group = MangoConstants["mainnet-beta"]
    print(f"Mango program ID: {mango_group['mango_program_id']}")
    for oracle in mango_group["oracles"]:
        print(f"Oracle [{oracle}]: {mango_group['oracles'][oracle]}")