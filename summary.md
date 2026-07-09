# UniswapV2Toolkit — Session Summary

This file documents the full session that produced the standalone Uniswap V2
LangChain toolkit in this directory. It exists so a fresh session in the new
dedicated project can pick up development with full context, without having
to re-derive decisions, re-run verifications, or repeat mistakes that were
already found and fixed here.

## 1. Why this exists

This toolkit was extracted from a larger project (`session-key-infra`): an
ERC-4337/ERC-7579 smart-contract wallet with session keys, spending limits,
and a LangChain-based conversational agent (`app/tools.py`,
`app/smart_wallet_agent.py` in the original repo) that lets an AI agent manage
ERC20 tokens, swap on Uniswap V2/PancakeSwap V2, provide liquidity, etc., all
scoped by on-chain, oracle-priced spending limits.

While discussing that project, a few things came up that led directly to this
toolkit:

- **LangChain ships zero blockchain-specific tools.** Verified directly
  against LangChain's own docs (via their MCP docs server) — the only
  blockchain-adjacent entry in their entire integrations corpus is a "Near
  Blockchain" *document loader* (NEAR-specific, read-only, unrelated to
  Ethereum/EVM). There is no Uniswap, no web3, no wallet integration anywhere
  in LangChain's prebuilt tools/toolkits.
- **Almost none of `app/tools.py`'s tools are portable.** They're all wired
  through `chat_id` → a SQLite DB → the project's own `SessionHandler`
  ERC-7579 contracts → Vault-encrypted session keys. None of that is reusable
  by a third party without redeploying the entire wallet stack.
- **The one genuinely portable cluster**: the *read-only* Uniswap V2 query
  tools — `get_quote_in`, `get_quote_out`, `get_pool_quote`, `get_lp_amounts`,
  `get_liquidity_token_balance`. These are pure on-chain reads via
  router/factory/pair contracts, with no wallet, session key, or DB
  involvement. That cluster is what got extracted and generalized into this
  toolkit.
- **Competitive landscape check** (for calibrating "is this actually novel"):
  compared against Coinbase's Agentic Wallets (MPC+TEE custodial, policy
  enforcement off-chain) and the `agent-wallet-sdk` GitHub repo (ERC-6551
  token-bound accounts, x402/Stripe/CCTP payment rails). Neither is a close
  competitor to *this specific toolkit* — they're agent-wallet products, not
  LangChain tool integrations. This toolkit's niche (a real, general-purpose
  LangChain-native Uniswap V2 toolkit) appears to be genuinely unoccupied,
  though "I couldn't find one" is not proof none exists.

**Intended use**: a standalone, `pip install`-able LangChain toolkit package —
both as a genuine open-source contribution (LangChain has no blockchain
tools; this fills a real gap) and as a portfolio/resume piece demonstrating
tool-integration design, not just wallet-specific plumbing.

## 2. Current file structure

```
app/toolkit/
├── uniswap_v2_toolkit.py   # UniswapV2Toolkit class + the 5 LangChain tools
├── abis.py                  # router_abi, factory_abi, pair_abi, erc20_abi
├── networks.py               # KNOWN_NETWORKS chain registry
└── summary.md                 # this file
```

All three code files are self-contained: **zero imports from the rest of the
original repo** (no `chat_id`, no `db.py`, no Vault, no `network_config.py`).
Only external dependencies are `web3` and `langchain_core`.

## 3. `uniswap_v2_toolkit.py` — design

### `UniswapV2Toolkit` class

```python
UniswapV2Toolkit(
    rpc_url: str,
    router_address: str,
    factory_address: str | None = None,   # auto-derived via router.factory() if omitted
    native_wrapped_address: str | None = None,  # enables 3-hop routing through this token
)
```

- Connects via `Web3.HTTPProvider(rpc_url)`, raises `ConnectionError` if the
  RPC doesn't respond to `is_connected()`.
- Binds `self.router` and `self.factory` as `web3.contract` instances using
  the ABIs imported from `abis.py`.
- `native_wrapped_address`, when set, is validated as a real checksummed
  address (`Web3.to_checksum_address`) — **it must be an address or `None`,
  never a ticker string**. This is important context: an earlier version of
  the chain registry considered storing a plain ticker like `"ETH"` here for
  chains where no wrapped-token address was known, which would crash
  immediately on `to_checksum_address("ETH")`. The fix was to add a *separate*
  `native_token` field (ticker, informational only, never passed to the
  constructor) in the registry instead — see §5.
- Internal caches (`_erc20_cache`, `_pair_cache`) keyed by address / address
  pair, so repeated tool calls against the same tokens don't refetch ABI
  bindings.

### `UniswapV2Toolkit.for_chain(chain_id, rpc_url=None)` classmethod

Convenience constructor: looks up `chain_id` in `KNOWN_NETWORKS`
(`networks.py`), and builds the toolkit from the registered router/factory/
native-wrapped address, defaulting to the registry's public RPC unless one is
passed explicitly. Raises `ValueError` with a clear message if:
- `chain_id` isn't in `KNOWN_NETWORKS`, or
- neither the caller nor the registry has an RPC URL for that chain (this
  happened for Tempo/Robinhood Chain before they were removed — see §6).

### The 5 tools (`get_tools()` returns these as `@tool`-wrapped closures over `self`)

All take **contract addresses**, not tickers — no ticker→address registry is
assumed, unlike the original `app/tools.py`.

1. **`get_quote_in(token_in, token_out, amount_out)`** — wraps
   `router.getAmountsIn`. "How much token_in do I need to receive exactly X
   token_out?"
2. **`get_quote_out(token_in, token_out, amount_in)`** — wraps
   `router.getAmountsOut`. "How much token_out will I get for X token_in?"
3. **`get_pool_quote(token_a, token_b, amount_a)`** — wraps `router.quote()`
   plus live pair reserves. Proportional deposit preview before adding
   liquidity.
4. **`get_lp_amounts(token_a, token_b, lp_amount)`** — proportional
   share-of-reserves redemption preview (`liquidity * reserve / totalSupply`)
   before removing liquidity.
5. **`get_liquidity_token_balance(owner_address, token_a, token_b)`** — LP
   token balance lookup for a given pair.

Both quote tools raise `ToolException` (not a bare exception — matches
LangChain's tool-error convention) on `ContractLogicError`, with a message
naming the token pair and suggesting the pool may not exist / lack reserves.

`_build_path(token_in, token_out)`: if a `native_wrapped_address` was
configured and neither token is that address, routes the quote through it
(2-hop → 3-hop path), mirroring how the original `app/tools.py` always
assumed WETH/WBNB routing. If no native-wrapped address is configured, always
uses a direct 2-hop path.

**Scope note**: this toolkit is **read-only only** — no swap execution, no
add/remove liquidity write calls. That was a deliberate scope cut (the
write-side tools in the original `app/tools.py` are inseparable from the
session-key wallet infrastructure), not an oversight. If write support is
ever added, it would need its own signer/transaction-submission story, which
this toolkit currently has no opinion on.

## 4. `abis.py` — how it was built, and a bug that was caught

Contains four Python list variables: `router_abi`, `factory_abi`, `pair_abi`,
`erc20_abi`.

**How it was generated**: not hand-transcribed. A Python script read the real
ABI JSON files from the original repo's `app/artifacts/*.json`
(`IUniswapV2Router02.json`, `IUniswapV2Factory.json`, `IUniswapV2Pair.json`,
`IERC20Extended.json`) and re-emitted them as formatted Python literals. This
was then diffed programmatically against the original JSON and confirmed
**byte-for-byte identical** (`generated_abi == json.load(f)["abi"]`) before
being written into the file.

**Bug caught along the way**: an earlier hand-written attempt at this file
(before the generate-and-diff approach was adopted) used raw JSON syntax
(`true`/`false`) instead of Python (`True`/`False`) inside the `PairCreated`
event definition in `factory_abi`. This made the file fail to *import at all*
(`NameError: name 'true' is not defined`). Lesson: when extracting ABIs (or
any JSON-derived data) into Python source, **generate programmatically and
diff against the source**, don't hand-transcribe — booleans are the most
common silent failure mode, and a plain `import` may not catch it if the
broken literal is inside a rarely-touched code path (here, an event
definition that nothing calls directly).

All four ABIs were also **live-tested** against real mainnet contracts (not
just syntax-checked): `router.factory()`, `weth.symbol()`,
`factory.allPairsLength()`, and confirming EntryPoint has contract code —
all returned correct, expected values.

## 5. `networks.py` — the chain registry

`KNOWN_NETWORKS: dict[int, dict]` keyed by chain ID. Each entry:

```python
{
    "name": str,            # human-readable slug, e.g. "mainnet", "bsc"
    "rpc_url": str | None,  # free public RPC default; None if none is known/reliable
    "router": str,          # router contract address
    "factory": str,         # factory contract address
    "native_wrapped": str | None,  # WETH/WBNB-equivalent address, or None if unverified
    "native_token": str,    # native gas asset ticker, e.g. "ETH", "BNB", "AVAX" -- informational only
}
```

**Why both `native_wrapped` and `native_token` exist** (a design point worth
preserving, since it wasn't obvious at first): `native_wrapped` must be a
real, valid address or `None` — it's fed straight into
`Web3.to_checksum_address()` in the constructor. `native_token` is a plain
ticker string for display/reference, included for *every* chain even where no
wrapped-token address is known, and is never passed anywhere that expects an
address. Merging these into one field would have crashed the constructor the
moment a chain with only a ticker (no known address) was used.

### Currently registered chains (13, after several rounds of live verification)

| chain_id | name | notes |
|---|---|---|
| 1 | mainnet | Uniswap V2, canonical addresses |
| 11155111 | sepolia | Uniswap V2 |
| 130 | unichain | Uniswap V2; default RPC was fixed (see §6) |
| 42161 | arbitrum | Uniswap V2 (Uniswap Labs' own redeploy, not a fork) |
| 43114 | avalanche | Uniswap V2 |
| 56 | bsc | **PancakeSwap V2**, not Uniswap Labs' own BSC redeploy — see §6 |
| 8453 | base | Uniswap V2; default RPC was fixed (see §6) |
| 10 | optimism | Uniswap V2 |
| 137 | polygon | Uniswap V2; default RPC was fixed (see §6); native_token is `"POL"` (post-MATIC-rebrand ticker) |
| 7777777 | zora | Uniswap V2 |
| 480 | worldchain | Uniswap V2 |
| 143 | monad | Uniswap V2 |
| 196 | x-layer | Uniswap V2; router address is unusual — see §6 |

All addresses are **Uniswap Labs' own official V2 redeployments** (sourced
from `https://developers.uniswap.org/docs/protocols/v2/deployments`, fetched
2026-07-08), **not** community forks (PancakeSwap, QuickSwap, SushiSwap,
TraderJoe, SpookySwap, Ubeswap, etc.) — except chain 56 (BSC), which
deliberately uses PancakeSwap instead (see §6, the BSC saga).

## 6. Investigations, mistakes caught, and fixes (read this before trusting any address in this file)

This is the part most worth preserving verbatim, because it's where real
bugs were found and real wrong assumptions were corrected. A future session
should not have to rediscover these.

### The BSC saga (PancakeSwap vs. Uniswap Labs' own BSC deployment)

The official Uniswap docs page lists Uniswap Labs' own V2 redeployment on
BSC (factory `0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6`, router
`0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24`) — this is **different** from
PancakeSwap (factory `0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73`, router
`0x10ED43C718714eb63d5aA57B78B54704E256024E`), which is what the original
`session-key-infra` project's own Solidity contracts actually use, and what
has by far the dominant liquidity on BSC.

The user initially chose to use Uniswap Labs' "official" deployment (since it
was the canonical source). **Live-testing that choice immediately surfaced a
real problem**: querying it for a 1 WBNB → BUSD quote returned **$0.25**,
off by roughly 1000x from BNB's real price — the pool exists on-chain and
responds to calls, but has near-zero/broken liquidity. The registry was then
switched back to PancakeSwap, which returns sane quotes (~$563 per WBNB,
matching real market price). **Lesson: "official" and "usable" are not the
same thing — a contract responding correctly to a view call does not mean
its pool has real liquidity. Always live-test an actual quote, not just
contract existence, before trusting a DEX deployment.**

### The X Layer / Monad address "collision" — assumed bug, disproven by testing

X Layer's registered router address
(`0x182a927119d56008d921126764bf884221b10f59`) is byte-for-byte identical to
Monad's registered factory address. This was initially (and reasonably)
assumed to be a copy-paste error in Uniswap's own docs table — a factory and
a router landing on the same CREATE2 address by chance seemed implausible.

**This assumption was wrong, and disproven by direct on-chain testing**:
calling `.factory()` on the X Layer address returned X Layer's correct,
registered factory address with a plausible non-zero `allPairsLength()`
(3579 pairs) — i.e., it's a genuinely live, correctly-functioning router on
X Layer. Separately, Monad's factory at the same hex string is also
confirmed live and correctly linked from Monad's own router. **Two different
chains are two entirely independent address spaces** — nothing prevents the
same hex address from hosting unrelated contracts on unrelated chains
(especially via deterministic/CREATE2-style deployment tooling, which
frequently produces identical addresses across chains by design). This was a
real analytical error that got corrected only because the on-chain
verification step was actually run instead of trusting the pattern-matching
intuition. **Lesson: a suspicious-looking coincidence is not a bug until
verified on-chain — cross-chain address reuse is normal, not evidence of a
copy-paste error.**

### MegaETH — confirmed dead, removed

MegaETH (chain_id 4326) was in an earlier version of the registry. Live
verification (`w3.eth.get_code(router_address)`) returned **zero bytecode**
at the registered router address — there is no contract deployed there at
all, despite the address being listed on Uniswap's official docs page. Likely
a testnet/mainnet address mismatch in the source documentation. **Removed
entirely** rather than kept with a warning, per the user's explicit choice.
If MegaETH support is wanted later, the addresses need to be re-sourced from
scratch, not reused from this session.

### Tempo and Robinhood Chain — removed by user's choice

Both were briefly in the registry (with `rpc_url: None`, forcing callers to
supply their own) but were removed at the user's explicit request, likely
because they're too new/niche to be worth maintaining. Their addresses were
never live-tested at all (unlike MegaETH, which was tested and found dead) —
if re-added later, treat them as **completely unverified**, not merely
"removed for cleanliness."

### Default public RPC URLs that were wrong and got fixed

Three chains' default `rpc_url` values failed to connect during testing and
were swapped for working alternatives:
- **Unichain**: `https://mainnet.unichain.org` → didn't connect →
  `https://unichain-rpc.publicnode.com`
- **Polygon**: `https://polygon-rpc.com` → didn't connect →
  `https://polygon-bor-rpc.publicnode.com`
- **Base**: `https://mainnet.base.org` → HTTP 429 (rate-limited) →
  `https://base.publicnode.com`

**Lesson: public RPC endpoints are not reliably stable defaults.** All
`rpc_url` values in `networks.py` are explicitly documented as "fine for
prototyping, rate-limited" — production users are expected to pass their own
via `for_chain(chain_id, rpc_url=...)`. If any chain starts failing to
connect in the new project, check the RPC default first before assuming the
router/factory addresses are wrong.

### The full verification methodology (worth reusing for any new chain added later)

Two independent passes were run across every registered chain, and both are
described inline in the `networks.py` module docstring:

1. **Structural check**: RPC connects, `router.functions.factory().call()`
   returns an address matching the registry's `factory` entry, and
   `factory.functions.allPairsLength().call()` is non-zero. This confirms the
   contracts are genuinely deployed and correctly linked to each other — not
   just that someone typed a plausible-looking address into a docs page.
2. **Functional/price-sanity check**: rather than guessing a token pair that
   might have liquidity (risky — could easily pick an untraded/rugged pair),
   a **real pair was pulled directly from the chain** via
   `factory.functions.allPairs(i)` for small `i` (checking up to ~12 pairs,
   picking the one with the largest minimum reserve as a crude liquidity
   proxy), then `get_quote_out` was called on that real pair and compared
   against the pair's raw reserve ratio. **Every single chain came back
   within ~0.310% of the implied reserve-ratio price** — which is *exactly*
   Uniswap V2's 0.3% swap fee. That consistent, exact match across 13
   unrelated chains is strong confirmation that the quote math itself is
   correct everywhere, not merely that calls don't crash.

If new chains are added to `KNOWN_NETWORKS` in the new project, **repeat both
checks** before trusting the entry — this methodology caught every real
problem found in this session (BSC's broken liquidity, MegaETH's dead
contract, three bad RPC defaults).

## 7. What's NOT done yet (explicit next steps, discussed but not started)

The user asked for an overall assessment of this toolkit as an open-source
contribution / resume piece. The conclusion: strong bones, but not yet
actually publishable. Specifically still missing:

1. **No test suite.** Everything above was verified via one-off scratch
   scripts during this session, not committed as `pytest` tests. A real
   contribution needs a `tests/` directory — likely a mix of mocked
   unit tests (fast, no network) and optional live/fork integration tests.
2. **No packaging.** No `pyproject.toml`/`setup.py`, no `README.md`, no
   `LICENSE`. LangChain's own contribution docs (confirmed via their MCP docs
   server) are explicit: **new integrations are not accepted as PRs into the
   `langchain-ai` monorepo** — they must be published as an independent
   package to PyPI, with only a docs-only PR submitted to
   `langchain-ai/docs` (using their `tools/TEMPLATE.mdx` template) pointing
   at it.
3. **No CI/lint config.**
4. **Read-only only** — no swap execution or liquidity write operations (see
   §3 scope note). Worth deciding explicitly whether this stays a "quotes and
   previews" toolkit or eventually grows a write-side story with its own
   signer abstraction.

These four items are the natural starting point for the next session in the
new project.

## 8. Quick reference — verified working examples

```python
from toolkit.uniswap_v2_toolkit import UniswapV2Toolkit

# Any Uniswap-V2-shaped DEX on any chain, explicit addresses:
toolkit = UniswapV2Toolkit(
    rpc_url="https://eth.llamarpc.com",
    router_address="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    native_wrapped_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
)

# A chain already in the registry:
toolkit = UniswapV2Toolkit.for_chain(chain_id=1)  # or 56 (bsc/PancakeSwap), 42161 (arbitrum), etc.

tools = toolkit.get_tools()
# -> [get_quote_in, get_quote_out, get_pool_quote, get_lp_amounts, get_liquidity_token_balance]

# Real, live-verified example (mainnet WETH -> USDC):
result = tools[1].invoke({  # get_quote_out
    "token_in": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH
    "token_out": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
    "amount_in": 1,
})
# -> {"amount_in": 1.0, "amount_out": ~1700-1740 (fluctuates with live price), "path": [...]}
```
