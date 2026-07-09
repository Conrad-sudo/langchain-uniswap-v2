# langchain-uniswap-v2

[![CI](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml)

Read-only [LangChain](https://www.langchain.com/) tools for querying Uniswap V2
(and Uniswap-V2-shaped fork, e.g. PancakeSwap) pools: swap quotes, liquidity
previews, and LP token balances — for any EVM chain, given just an RPC URL
and contract addresses.

LangChain ships no blockchain-specific tools out of the box. This package
fills that gap for the Uniswap V2 AMM shape specifically.

## Scope

This package is **read-only**. It answers questions like "how much will I
get" and "how much do I need" — it does not execute swaps or add/remove
liquidity. Wiring up transaction signing/submission is left to the caller.

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
# -> [get_quote_in, get_quote_out, get_pool_quote,
#     get_lp_amounts, get_liquidity_token_balance]

# Pass tools directly into an agent:
#   agent = create_agent(model, tools=tools)

# Or call a tool directly:
result = tools[1].invoke({  # get_quote_out
    "token_in": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH
    "token_out": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
    "amount_in": 1,
})
# -> {"amount_in": 1.0, "amount_out": <live price>, "path": [...]}
```

`UniswapV2Toolkit.for_chain(...)` accepts an optional `rpc_url=` override —
the registry's default is a free public endpoint, fine for prototyping but
rate-limited. Pass your own (Alchemy, Infura, etc.) for production use.

## Tools

All tools take plain contract addresses as arguments — no ticker→address
registry is assumed.

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
