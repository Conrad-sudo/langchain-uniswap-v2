# langchain-uniswap-v2

[![CI](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/langchain-uniswap-v2)](https://pypi.org/project/langchain-uniswap-v2/)

[LangChain](https://www.langchain.com/) tools for Uniswap V2 (and
Uniswap-V2-shaped forks, e.g. PancakeSwap): live swap quotes, liquidity
previews, LP token balances, and unsigned transactions for swaps, approvals,
and add/remove liquidity — for any EVM chain, given just an RPC URL and
contract addresses.

LangChain's existing blockchain integrations are Coinbase's CDP AgentKit
(execution-oriented — transfers, trades, deployments — tied to Coinbase's
own wallet infrastructure) and the Compass DeFi Toolkit (a paid third-party
API that returns unsigned transactions across several protocols, including
Uniswap). Neither is a free, permissionless toolkit that works against any
EVM chain given just an RPC URL — no API key, no third-party service, no
wallet required. This package fills that specific gap for the Uniswap V2
AMM shape.

## Scope

This package never holds a private key, a signer, or any wallet state, and
it never signs or submits a transaction. Read tools (quotes, liquidity
previews, balances) only make RPC calls. Write tools (approvals, swaps,
add/remove liquidity) build and return a plain **unsigned transaction
dict** — the caller signs and submits it with whatever wallet
infrastructure they already have (a local key, a KMS-backed signer, a
smart-contract wallet). See [Write tools](#write-tools-unsigned-transactions)
below.

## Install

```bash
pip install langchain-uniswap-v2
```

For local development (editable install + test dependencies):

```bash
pip install -e ".[dev]"
```

## Quick start

```python
from langchain_uniswap_v2 import UniswapV2Toolkit

# Any Uniswap-V2-shaped DEX, on any chain, via explicit addresses:
toolkit = UniswapV2Toolkit(
    rpc_url="https://eth.llamarpc.com",
    router_address="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    native_wrapped_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
)

# Or, for a chain already in the built-in registry, just pass a chain_id:
toolkit = UniswapV2Toolkit.for_chain(chain_id=1)  # mainnet
# toolkit = UniswapV2Toolkit.for_chain(chain_id=56)  # bsc (PancakeSwap)

tools = toolkit.get_tools()
# -> [get_quote_in, get_quote_out, get_pool_quote, get_lp_amounts,
#     get_liquidity_token_balance, is_token_balance_sufficient,
#     is_native_balance_sufficient, is_derived_token_input_sufficient,
#     is_derived_native_input_sufficient, is_liquidity_sufficient,
#     is_liquidity_sufficient_eth, is_liquidity_removal_sufficient,
#     approve_token,
#     swap_exact_tokens_for_tokens, swap_tokens_for_exact_tokens,
#     swap_exact_eth_for_tokens, swap_eth_for_exact_tokens,
#     swap_exact_tokens_for_eth, swap_tokens_for_exact_eth,
#     add_liquidity, add_liquidity_eth,
#     remove_liquidity, remove_liquidity_eth]

# Pass tools directly into an agent:
#   agent = create_agent(model, tools=tools)

# Or call a tool directly:
result = tools[1].invoke(
    {  # get_quote_out
        "token_in": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "token_out": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "amount_in": 1,
    }
)
# -> {"amount_in": 1.0, "amount_out": <live price>, "path": [...]}
```

`UniswapV2Toolkit.for_chain(...)` accepts an optional `rpc_url=` override —
the registry's default is a free public endpoint, fine for prototyping but
rate-limited. Pass your own (Alchemy, Infura, etc.) for production use.

## Tools

All tools take plain contract addresses as arguments — no ticker→address
registry is assumed.

### Read tools

| Tool | Purpose |
|---|---|
| `get_quote_in(token_in, token_out, amount_out)` | How much `token_in` is needed to receive an exact `amount_out` of `token_out`. |
| `get_quote_out(token_in, token_out, amount_in)` | How much `token_out` will be received for an exact `amount_in` of `token_in`. |
| `get_pool_quote(token_a, token_b, amount_a)` | Proportional `token_b` deposit required to match a given `token_a` deposit, before adding liquidity. |
| `get_lp_amounts(token_a, token_b, lp_amount)` | Expected token amounts redeemable for a given amount of LP tokens, before removing liquidity. |
| `get_liquidity_token_balance(owner_address, token_a, token_b)` | An address's LP token balance for a given pair. |

If `native_wrapped_address` is configured, quotes between two non-native
tokens are routed through it (2-hop → 3-hop path), matching how Uniswap V2
pools are typically seeded. Without it, quotes always use a direct path.

Balance-sufficiency checks answer "does this address hold enough" before a
write tool would actually be called, given an explicit `owner_address` —
useful for an agent to check before spending gas building/submitting a
transaction that would just revert. Each mirrors the balance requirement of
one or two write tools below:

| Tool | Checks balance for |
|---|---|
| `is_token_balance_sufficient(token_address, amount, owner_address)` | An exact ERC20 amount — e.g. before `approve_token` or an exact-input swap. |
| `is_native_balance_sufficient(amount, owner_address)` | An exact native-asset amount. |
| `is_derived_token_input_sufficient(token_in, token_out, amount_out, owner_address, slippage_bps=50)` | `swap_tokens_for_exact_tokens` / `swap_tokens_for_exact_eth` — required input is derived from a live quote plus slippage. |
| `is_derived_native_input_sufficient(token_out, amount_out, owner_address, slippage_bps=50)` | `swap_eth_for_exact_tokens`. |
| `is_liquidity_sufficient(token_a, amount_a, token_b, owner_address)` | `add_liquidity` — both token amounts, the second derived from live reserves. |
| `is_liquidity_sufficient_eth(token, amount_token, owner_address)` | `add_liquidity_eth`. |
| `is_liquidity_removal_sufficient(token_a, token_b, lp_amount, owner_address)` | `remove_liquidity` / `remove_liquidity_eth` — LP token balance. |

### Write tools (unsigned transactions)

Every write tool returns a plain transaction dict (`to`, `data`, `value`,
`gas`, `nonce`, `chainId`, ...) built via `web3.py`'s `build_transaction` —
nothing is signed or sent. Each takes an explicit `from_address` (used to
read the nonce and set as the recipient of swap/liquidity output), and none
of them require a session key, a signer object, or any wallet state on the
toolkit itself.

| Tool | Purpose |
|---|---|
| `approve_token(token_address, spender_address, amount, from_address)` | Unsigned ERC20 `approve`. Needed before any tool below that pulls tokens from `from_address` — approve and act are always separate transactions here, since there's no session-key-style atomic batching to lean on. |
| `swap_exact_tokens_for_tokens` / `swap_tokens_for_exact_tokens` | Token-for-token swaps, exact-input or exact-output. |
| `swap_exact_eth_for_tokens` / `swap_eth_for_exact_tokens` | Native-asset-for-token swaps (requires `native_wrapped_address`). |
| `swap_exact_tokens_for_eth` / `swap_tokens_for_exact_eth` | Token-for-native-asset swaps (requires `native_wrapped_address`). |
| `add_liquidity` / `add_liquidity_eth` | Deposit into a pool; the paired amount is derived from live reserves so the deposit matches the current pool ratio. |
| `remove_liquidity` / `remove_liquidity_eth` | Burn LP tokens for both underlying tokens, using live reserves to compute expected returns. |

All amount-based write tools take `slippage_bps` (default `50` = 0.5%) and
derive `amountOutMin`/`amountInMax`/equivalent from a live on-chain quote,
plus `deadline_secs` (default `600`) for the transaction's on-chain expiry
— both are always explicit, never silently applied. Every write tool also
accepts an optional `nonce` override, useful when building more than one
unsigned transaction in sequence (e.g. `approve_token` then a swap) before
submitting either, so the two nonces don't collide.

"ETH" in tool/parameter names is a generic internal label for the chain's
native asset (ETH, BNB, etc.) — it works identically on every supported
network.

## Supported chains (built-in registry)

All addresses are Uniswap Labs' own official V2 redeployments, except BSC,
which deliberately uses PancakeSwap — see the note below.

| chain_id | name | native_token |
|---|---|---|
| 1 | mainnet | ETH |
| 11155111 | sepolia | ETH |
| 130 | unichain | ETH |
| 42161 | arbitrum | ETH |
| 43114 | avalanche | AVAX |
| 56 | bsc (PancakeSwap V2) | BNB |
| 8453 | base | ETH |
| 10 | optimism | ETH |
| 137 | polygon | POL |
| 7777777 | zora | ETH |
| 480 | worldchain | ETH |
| 143 | monad | MON |
| 196 | x-layer | OKB |

**Why BSC uses PancakeSwap, not Uniswap Labs' own BSC redeployment:** the
official Uniswap Labs BSC contracts exist and respond to calls, but were
live-tested and found to have near-zero liquidity (returning wildly
incorrect quotes). PancakeSwap has the actual liquidity on BSC, so the
registry points there instead.

For any chain not listed here, instantiate `UniswapV2Toolkit(...)` directly
with explicit `router_address` / `factory_address` / `native_wrapped_address`.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

The test suite mocks all contract calls (see `tests/web3_mocks.py`) — it
makes no live network calls, so it runs fast and doesn't depend on any RPC
endpoint being up.

`langchain_uniswap_v2/abis.py` is machine-generated from the original ABI
JSON and verified byte-for-byte against it — it's excluded from Ruff so
lint/format never churns it.

CI (`.github/workflows/ci.yml`) runs `ruff check`/`ruff format --check` and
the test suite (Python 3.10–3.12) on every push and pull request.

## License

MIT — see [LICENSE](LICENSE).
