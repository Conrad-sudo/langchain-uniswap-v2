# langchain-uniswap-v2

[![CI](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/Conrad-sudo/langchain-uniswap-v2/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/langchain-uniswap-v2)](https://pypi.org/project/langchain-uniswap-v2/)
[![Python](https://img.shields.io/pypi/pyversions/langchain-uniswap-v2)](https://pypi.org/project/langchain-uniswap-v2/)
[![License](https://img.shields.io/pypi/l/langchain-uniswap-v2)](https://github.com/Conrad-sudo/langchain-uniswap-v2/blob/main/LICENSE)

[LangChain](https://www.langchain.com/) tools for Uniswap V2 (and
Uniswap-V2-shaped forks, e.g. PancakeSwap): live swap quotes, liquidity
previews, LP token balances, and execution plans for swaps, approvals, and
add/remove liquidity — ready for an EOA to sign or a smart-contract wallet
to batch, on any EVM chain, given just an RPC URL and contract addresses.

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
add/remove liquidity) build and return an **execution plan** — an ordered
list of account-agnostic contract calls, ready for an EOA to sign or a
smart-contract wallet to batch. See [Execution modes](#execution-modes) and
[Write tools](#write-tools-execution-plans) below.

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

A second example, for a smart-contract wallet consuming calls directly
instead of signing EOA transactions:

```python
scw_toolkit = UniswapV2Toolkit.for_chain(chain_id=1, tx_mode="calls")
scw_tools = {t.name: t for t in scw_toolkit.get_tools()}

plan = scw_tools["swap_exact_tokens_for_tokens"].invoke(
    {
        "token_in": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "token_out": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "amount_in": 1,
        "from_address": "0xYourSmartAccount...",
    }
)
# plan["transactions"] is None -- zero nonce/gas/fee RPC calls were made.
executions = [(c["to"], c["value"], bytes.fromhex(c["data"][2:])) for c in plan["calls"]]
# feed `executions` into your account's own batch executor, e.g. an
# ERC-7579 execute(mode, abi.encode(executions)) call.
```

## Execution modes

Every write tool returns a **plan**, not a bare transaction:

```python
{
    "calls": [  # always present, ordered -- execute all of them
        {"to": "0x...", "value": 0, "data": "0x...", "role": "approve", "description": "..."},
        {
            "to": "0x...router",
            "value": 0,
            "data": "0x...",
            "role": "swap",
            "description": "...",
        },
    ],
    "transactions": [...] | None,  # EOA mode only; same calls, signable, nonces assigned
    "gas_estimated": [...] | None,  # EOA mode only; per tx, live estimate or DEFAULT_GAS
    "chain_id": 1,
    "summary": {...},  # amounts in whole units, safe to show a user
}
```

- **`tx_mode="eoa"`** (the default) also renders `plan["transactions"]`: the
  same calls as unsigned, signable transactions with sequential nonces
  already assigned. Sign and broadcast them in order.
- **`tx_mode="calls"`** returns `calls` only (`transactions` is `None`) and
  makes **zero** nonce/gas/fee RPC calls — for a smart-contract wallet's own
  batch executor.

`calls` is the smallest primitive both audiences agree on: an EOA
transaction is `(to, value, data)` plus nonce/gas/fees; an ERC-7579
`Execution` is exactly `(to, value, data)`. Execute every call in a plan, in
order — if your account supports batching, execute them atomically in one
transaction. That atomicity is what makes the approve → action → reset
sequence safe for accounts that reject standing approvals.

**`gas_estimated` (EOA mode):** a call whose prerequisite approval is earlier
in the same plan can't be simulated yet — the allowance isn't on-chain until
that earlier call is mined. For those, the transaction's `gas` field falls
back to a static per-role default (`DEFAULT_GAS`) and the matching entry in
`plan["gas_estimated"]` is `False`, flagging that the limit wasn't derived
from a live simulation and should be sanity-checked before broadcast. Only
the **first** call in a plan has its revert treated as fatal — if that one
fails to estimate, the tool raises `ToolException` instead of returning a
plan that would fail on-chain.

The flags live on the plan, index for index with `transactions`, rather than
inside the transaction dicts: a transaction dict holds transaction fields and
nothing else, so it signs exactly as returned. `eth_account` validates its
input and rejects an unrecognised key with `TypeError: Unknown kwargs`, so a
stray flag would break the first thing every EOA consumer does.

**Constructor options**, all keyword-only:

| Param | Default | Meaning |
|---|---|---|
| `tx_mode` | `"eoa"` | `"eoa"` also renders `transactions`. `"calls"` returns calls only. |
| `estimate_gas` | `True` | EOA mode only. `False` uses `default_gas` for every call, skipping live `eth_estimateGas`. |
| `gas_buffer` | `1.25` | Multiplier applied to a successful gas estimate. |
| `default_gas` | `None` | Per-role fallback gas limits, merged over the module's `DEFAULT_GAS`. |
| `reset_residual_approvals` | `None` | Append a trailing zero-approval where needed (see [Write tools](#write-tools-execution-plans)). Defaults to `True` in `"calls"` mode, `False` in `"eoa"` mode. |
| `preflight` | `True` | Run the matching balance-sufficiency check before building, raising `ToolException` (naming the shortfall) if it fails. |

`UniswapV2Toolkit.for_chain(chain_id, rpc_url=None, **kwargs)` forwards
`**kwargs` to the constructor, so e.g.
`UniswapV2Toolkit.for_chain(1, tx_mode="calls", preflight=False)` works.
`router_address`, `factory_address` and `native_wrapped_address` can be
passed the same way, each overriding the registry's value for that chain —
the escape hatch for a stale entry, or a fork or testnet reusing a known
chain id.

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

For a `token_in`/`token_out` pair, the direct pool and — when
`native_wrapped_address` is configured — the route through the wrapped
native are both quoted, and the better fill wins: more `token_out` for an
exact-input quote, less `token_in` for an exact-output one. An exact tie
goes to the direct pool, since one hop costs less gas than two. A route that
reverts is skipped; if none is routable the tool raises `ToolException`.

Comparing beats assuming in both directions. Routing a liquid USDC/DAI pair
through WETH would pay the 0.3% fee twice and take two price impacts instead
of one, so the direct pool usually wins — but a direct pool holding dust
loses badly, and picking it on the strength of merely existing is a silent
error, because `amount_out_min` is derived from the same quote and the swap
then fills "within tolerance" at a much worse price.

Balance-sufficiency checks answer "does this address hold enough" before a
write tool would actually be called, given an explicit `owner_address` —
useful for an agent to check before spending gas building/submitting a
transaction that would just revert. Every write tool below already runs its
matching check automatically before building (see `preflight` above); these
tools are for checking ahead of time or with `preflight=False`. Each mirrors
the balance requirement of one or two write tools below:

| Tool | Checks balance for |
|---|---|
| `is_token_balance_sufficient(token_address, amount, owner_address)` | An exact ERC20 amount — e.g. before `approve_token` or an exact-input swap. |
| `is_native_balance_sufficient(amount, owner_address)` | An exact native-asset amount. |
| `is_derived_token_input_sufficient(token_in, token_out, amount_out, owner_address, slippage_bps=50)` | `swap_tokens_for_exact_tokens` / `swap_tokens_for_exact_eth` — required input is derived from a live quote plus slippage. |
| `is_derived_native_input_sufficient(token_out, amount_out, owner_address, slippage_bps=50)` | `swap_eth_for_exact_tokens`. |
| `is_liquidity_sufficient(token_a, amount_a, token_b, owner_address)` | `add_liquidity` — both token amounts, the second derived from live reserves. |
| `is_liquidity_sufficient_eth(token, amount_token, owner_address)` | `add_liquidity_eth`. |
| `is_liquidity_removal_sufficient(token_a, token_b, lp_amount, owner_address)` | `remove_liquidity` / `remove_liquidity_eth` — LP token balance. |

### Write tools (execution plans)

Every write tool below includes its own approval call(s) in the plan
automatically, sized to what that call actually needs — you no longer need
to call `approve_token` first. `approve_token` remains available for
explicit/manual control (e.g. granting an allowance outside of any swap or
deposit flow, or to a spender other than this toolkit's router), and takes
an `unlimited=True` option for the standard effectively-unlimited approval
instead of passing an arbitrary large `amount`.

| Tool | Approves | Reset needed |
|---|---|---|
| `approve_token(token_address, spender_address, from_address, amount=0, unlimited=False)` | is itself the approval | — |
| `swap_exact_tokens_for_tokens` / `swap_exact_tokens_for_eth` | `token_in`, the exact amount sold | no — exact pull |
| `swap_tokens_for_exact_tokens` / `swap_tokens_for_exact_eth` | `token_in`, the derived max | yes, when the router pulls less |
| `swap_exact_eth_for_tokens` / `swap_eth_for_exact_tokens` | — (native value, no approval needed) | — |
| `add_liquidity` / `add_liquidity_eth` | the token(s) deposited | yes — pool ratio may consume less |
| `remove_liquidity` / `remove_liquidity_eth` | the pair's own LP token, the exact amount burned | no — exact pull |

"Reset needed" means: when the router may pull less than it was approved
for, the plan appends a trailing `approve(spender, 0)` call — but only when
`reset_residual_approvals` is enabled (see [Execution modes](#execution-modes)).
Tools that always pull their exact approved amount never append one,
regardless of that setting, since there is nothing left to clear.

All amount-based write tools also take `slippage_bps` (default `50` = 0.5%)
and derive `amountOutMin`/`amountInMax`/equivalent from a live on-chain
quote, and `deadline_secs` (default `600`) for the plan's on-chain expiry —
both are always explicit, never silently applied. Every write tool also
takes an optional `recipient` (defaults to `from_address`) for the output of
the call — the account executing the plan and the account receiving the
result don't have to be the same address — and an optional `nonce`: the
*starting* nonce for the plan in EOA mode (later calls increment from it
automatically), ignored entirely in `"calls"` mode.

"ETH" in tool/parameter names is a generic internal label for the chain's
native asset (ETH, BNB, etc.) — it works identically on every supported
network.

## Supported chains (built-in registry)

All addresses are Uniswap Labs' own official V2 redeployments, except BSC,
which deliberately uses PancakeSwap — see the note below.

| chain_id | name | native_token | wrapped native |
|---|---|---|---|
| 1 | mainnet | ETH | WETH |
| 11155111 | sepolia | ETH | WETH |
| 130 | unichain | ETH | WETH |
| 42161 | arbitrum | ETH | WETH |
| 43114 | avalanche | AVAX | WAVAX |
| 56 | bsc (PancakeSwap V2) | BNB | WBNB |
| 8453 | base | ETH | WETH |
| 10 | optimism | ETH | WETH |
| 137 | polygon | POL | WPOL |
| 7777777 | zora | ETH | WETH |
| 480 | worldchain | ETH | WETH |
| 143 | monad | MON | WMON |
| 196 | x-layer | OKB | WOKB |

Every chain has a wrapped-native address registered, so the native-asset
swap and liquidity tools work on all of them. Each address is the one that
chain's own router returns from `WETH()` — the router rejects any other
address in its `*ETH`-suffixed functions with `UniswapV2Router:
INVALID_PATH`, so the router is the only authority on this, not a token list
or explorer page. `scripts/verify_native_wrapped.py` re-checks every entry
against its live router (weekly in CI, and runnable locally).

**Why BSC uses PancakeSwap, not Uniswap Labs' own BSC redeployment:** the
official Uniswap Labs BSC contracts exist and respond to calls, but were
live-tested and found to have near-zero liquidity (returning wildly
incorrect quotes). PancakeSwap has the actual liquidity on BSC, so the
registry points there instead.

For any chain not listed here, instantiate `UniswapV2Toolkit(...)` directly
with explicit `router_address` / `factory_address` / `native_wrapped_address`.

## Migration (0.4.0 → 0.5.0)

One shape change, in the EOA path only. `calls` mode is untouched.

**Changed**

- `gas_estimated` moved out of each transaction dict and onto the plan as
  `plan["gas_estimated"]` — a list of one bool per transaction, index for
  index with `plan["transactions"]`, and `None` in calls mode.

Why: a transaction dict now holds transaction fields and nothing else, so it
signs exactly as returned. Previously
`eth_account.sign_transaction(plan["transactions"][0])` raised
`TypeError: Unknown kwargs: ['gas_estimated']`, and this README told callers
to pop the key first.

| behaviour | 0.4.0 | 0.5.0 |
|---|---|---|
| `acct.sign_transaction(plan["transactions"][0])` | `TypeError: Unknown kwargs` | signs |
| reading the flag | `plan["transactions"][i]["gas_estimated"]` | `plan["gas_estimated"][i]` |
| `tx.pop("gas_estimated")` in a signing loop | required | `KeyError` — delete the line |
| calls mode | unaffected | unaffected |

If your signing loop used the tolerant `tx.pop("gas_estimated", None)`, it
keeps working as written; the strict `tx.pop("gas_estimated")` now raises and
the line should simply be removed.

## Migration (0.3.0 → 0.4.0)

No API change: nothing renamed, no signature removed, no return shape
altered. Existing code keeps working as written. It is a minor rather than a
patch because observable behaviour changes for existing callers.

**Added**

- `native_wrapped` is now populated for all supported chains (previously
  `None` on 10 of 13), enabling the native-asset swap and liquidity tools
  and wrapped-native multi-hop routing on Optimism, Polygon, Base, Arbitrum,
  Avalanche, Unichain, Monad, X Layer, World Chain and Zora. Every value is
  verified equal to the chain router's own `WETH()`.

**Fixed**

- `for_chain()` no longer raises `TypeError` when a caller overrides
  `router_address`, `factory_address` or `native_wrapped_address`.
- Route selection no longer prefers a direct pair holding negligible
  reserves over a wrapped-native route that quotes better. Previously this
  could select a materially worse price with no error at all.

What this means in practice:

| behaviour | 0.3.0 | 0.4.0 |
|---|---|---|
| eight native-asset tools on 10 of the 13 chains | raise `ToolException` when invoked | build plans |
| token→token pairs with no direct pool, on those chains | raise "no liquidity path" | route through the wrapped native |
| direct pool holding dust, better route available | silently takes the dust pool | takes the better route |
| `for_chain(cid, native_wrapped_address=...)` | `TypeError` | override applied |

If you pinned around any of that — for example, passing
`native_wrapped_address` explicitly to work around the missing registry
values, or hard-coding a path you expected the toolkit to produce — the
workarounds still function, but are no longer needed.

## Migration (0.2.0 → 0.3.0)

Read tools are unchanged. Write tools now return an execution plan instead
of a bare transaction dict:

| 0.2.0 | 0.3.0 |
|---|---|
| `tx = tool.invoke(...)` → bare tx dict | `plan = tool.invoke(...)` → plan dict |
| `sign(tx)` | `for tx in plan["transactions"]: sign(tx)` |
| caller calls `approve_token` separately | approval is `plan["calls"][0]`, already sized |
| caller manages `nonce` collisions | nonces pre-assigned across the plan |
| caller re-quotes to describe the swap | `plan["summary"]` |
| build raises when allowance missing | builds fine; `plan["gas_estimated"]` flags fallbacks |

Minimal EOA diff:

```diff
-tx = tools["swap_exact_tokens_for_tokens"].invoke({...})
-signed = acct.sign_transaction(tx)
-w3.eth.send_raw_transaction(signed.raw_transaction)
+plan = tools["swap_exact_tokens_for_tokens"].invoke({...})
+for tx in plan["transactions"]:
+    signed = acct.sign_transaction(tx)
+    w3.eth.send_raw_transaction(signed.raw_transaction)
```

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

`scripts/verify_native_wrapped.py` checks the registry against the live
chains — router bytecode present, `WETH()` and `factory()` matching the
table — and reports each wrapped native's symbol and decimals. It runs
weekly via `.github/workflows/verify-networks.yml` rather than on pull
requests, so PR CI stays offline and deterministic. An unreachable endpoint
is a skip; a mismatch fails. Point it at your own endpoints with
`UNISWAP_V2_RPC_<chain_id>`:

```bash
python scripts/verify_native_wrapped.py            # every entry
python scripts/verify_native_wrapped.py --chain 1  # just one
UNISWAP_V2_RPC_137=https://your-endpoint python scripts/verify_native_wrapped.py --chain 137
```

## License

MIT — see [LICENSE](LICENSE).
