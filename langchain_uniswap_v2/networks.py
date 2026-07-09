# All router/factory addresses below are Uniswap Labs' own official V2
# redeployments, sourced from https://developers.uniswap.org/docs/protocols/v2/deployments
# (fetched 2026-07-08) -- NOT community forks (PancakeSwap, QuickSwap, SushiSwap,
# TraderJoe, SpookySwap, Ubeswap, etc.), which use entirely different
# addresses and are often far more liquid on their chain than Uniswap Labs'
# own redeployment. Exception: chain_id 56 below is PancakeSwap, not Uniswap
# Labs' own BSC redeploy -- the latter was live-tested and returns garbage
# quotes due to near-zero liquidity, so PancakeSwap (what this repo's own
# Solidity contracts target) is used instead.
#
# Verification status (all 13 entries below re-verified 2026-07-08, two
# passes): (1) RPC connects, router.factory() matches the registered factory
# address, and the factory's allPairsLength() is non-zero -- confirms
# genuinely deployed, linked contracts, not just addresses copied from docs.
# (2) A real, live pool was pulled directly off each chain's factory
# (factory.allPairs(i), not a guessed token address), and get_quote_out's
# returned price was compared against the pool's raw reserve ratio -- every
# chain came back within ~0.31% of the implied price, which is exactly
# Uniswap V2's 0.3% swap fee. That match confirms the quote math itself is
# correct on every chain, not just that the contracts respond.
#   - Mainnet, BSC: additionally cross-checked against this repo's own
#     script/Constants.s.sol.
#   - Sepolia, Unichain, Arbitrum, Avalanche, Base, Optimism, Polygon, Zora,
#     WorldChain, Monad, X Layer: all pass both checks above.
#   - X Layer's router address happens to equal Monad's factory address --
#     initially assumed to be a docs copy-paste error, but on-chain testing
#     disproved that: both are independently live, correctly-linked contracts
#     on their respective (unrelated) chains. Address reuse across different
#     chains via deterministic (CREATE2-style) deployment is expected, not a bug.
#   - MegaETH was removed: its registered router address has zero contract
#     bytecode on mainnet (chain_id 4326) -- confirmed dead, likely a
#     testnet/mainnet address mismatch in the source docs.
#   - native_token is the chain's native gas asset ticker, included per-chain
#     even where no wrapped-native address is known; it is NOT a valid
#     address and must not be passed as native_wrapped_address.
#
# rpc_url is a free public endpoint -- fine for prototyping, but rate-limited;
# pass your own (Alchemy/Infura/etc.) via for_chain(..., rpc_url=...) for
# production use. Chains with no known Uniswap V2 (or fork) deployment are
# omitted rather than guessed -- use the main constructor with explicit
# addresses for any chain not listed here.
KNOWN_NETWORKS: dict[int, dict] = {
    1: {  # Ethereum Mainnet -- Uniswap V2
        "name": "mainnet",
        "rpc_url": "https://ethereum.publicnode.com",
        "router": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "native_wrapped": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "native_token": "ETH",
    },
    11155111: {  # Sepolia -- Uniswap V2
        "name": "sepolia",
        "rpc_url": "https://ethereum-sepolia-rpc.publicnode.com",
        "router": "0xeE567Fe1712Faf6149d80dA1E6934E354124CfE3",
        "factory": "0xF62c03E08ada871A0bEb309762E260a7a6a880E6",
        "native_wrapped": "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",  # WETH
        "native_token": "ETH",
    },
    130: {  # Unichain -- Uniswap V2
        "name": "unichain",
        "rpc_url": "https://unichain-rpc.publicnode.com",
        "router": "0x284f11109359a7e1306c3e447ef14d38400063ff",
        "factory": "0x1f98400000000000000000000000000000000002",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    42161: {  # Arbitrum One -- Uniswap V2
        "name": "arbitrum",
        "rpc_url": "https://arb1.arbitrum.io/rpc",
        "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "factory": "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    43114: {  # Avalanche C-Chain -- Uniswap V2
        "name": "avalanche",
        "rpc_url": "https://api.avax.network/ext/bc/C/rpc",
        "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "factory": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
        "native_wrapped": None,
        "native_token": "AVAX",
    },
    56: {  # BNB Smart Chain -- PancakeSwap V2. Uniswap Labs also has an
        # official V2 redeploy on BSC (factory 0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6,
        # router 0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24) but it was
        # live-tested here and returns garbage quotes (1 WBNB ~= $0.25) due
        # to near-zero liquidity -- PancakeSwap is what's actually used on this chain
        "name": "bsc",
        "rpc_url": "https://bsc-dataseed.binance.org",
        "router": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        "factory": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
        "native_wrapped": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
        "native_token": "BNB",
    },
    8453: {  # Base -- Uniswap V2
        "name": "base",
        "rpc_url": "https://base.publicnode.com",
        "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    10: {  # Optimism -- Uniswap V2
        "name": "optimism",
        "rpc_url": "https://mainnet.optimism.io",
        "router": "0x4A7b5Da61326A6379179b40d00F57E5bbDC962c2",
        "factory": "0x0c3c1c532F1e39EdF36BE9Fe0bE1410313E074Bf",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    137: {  # Polygon PoS -- Uniswap V2
        "name": "polygon",
        "rpc_url": "https://polygon-bor-rpc.publicnode.com",
        "router": "0xedf6066a2b290C185783862C7F4776A2C8077AD1",
        "factory": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
        "native_wrapped": None,
        "native_token": "POL",  # formerly MATIC
    },
    7777777: {  # Zora -- Uniswap V2
        "name": "zora",
        "rpc_url": "https://rpc.zora.energy",
        "router": "0xa00F34A632630EFd15223B1968358bA4845bEEC7",
        "factory": "0x0F797dC7efaEA995bB916f268D919d0a1950eE3C",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    480: {  # World Chain -- Uniswap V2
        "name": "worldchain",
        "rpc_url": "https://worldchain-mainnet.g.alchemy.com/public",
        "router": "0x541aB7c31A119441eF3575F6973277DE0eF460bd",
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "native_wrapped": None,
        "native_token": "ETH",
    },
    143: {  # Monad -- Uniswap V2
        "name": "monad",
        "rpc_url": "https://rpc.monad.xyz",
        "router": "0x4b2ab38dbf28d31d467aa8993f6c2585981d6804",
        "factory": "0x182a927119d56008d921126764bf884221b10f59",
        "native_wrapped": None,
        "native_token": "MON",
    },
    196: {  # X Layer -- Uniswap V2. See KNOWN ISSUE above: router address is
        # suspect (duplicate of Monad's factory) -- verify independently.
        "name": "x-layer",
        "rpc_url": "https://rpc.xlayer.tech",
        "router": "0x182a927119d56008d921126764bf884221b10f59",  # UNVERIFIED, see note above
        "factory": "0xDf38F24fE153761634Be942F9d859f3DBA857E95",
        "native_wrapped": None,
        "native_token": "OKB",
    },
}
