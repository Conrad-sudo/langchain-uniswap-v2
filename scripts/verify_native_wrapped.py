"""
Verifies every KNOWN_NETWORKS entry against the chain it claims to describe.

The authority on a chain's wrapped native is the router itself: each Uniswap
V2 router stores the wrapped-native it was deployed against and exposes it as
WETH(), and it rejects any other address in its *ETH-suffixed functions with
"UniswapV2Router: INVALID_PATH". So native_wrapped is correct if and only if
it equals router.WETH() -- a plausible address taken from a token list that
disagrees with the router produces a hard revert at swap time, not a warning.

For each entry this asserts:
  1. the router address has non-empty bytecode;
  2. router.WETH() equals native_wrapped (case-insensitive);
  3. router.factory() equals factory (case-insensitive);
  4. native_wrapped is set at all -- every supported chain has a resolvable
     wrapped native, so None is a gap, not a legitimate state;
and reports symbol()/decimals() of the wrapped native for eyeballing.

RPC endpoints: the registry's own free public endpoint is used by default.
Override per chain with UNISWAP_V2_RPC_<chain_id>, e.g.

    UNISWAP_V2_RPC_137=https://polygon-mainnet.g.alchemy.com/v2/KEY \\
        python scripts/verify_native_wrapped.py

An unreachable endpoint is a SKIP, not a failure, so transient public-endpoint
outages don't fail CI; pass --require-all to turn skips into failures for a
run you need to be exhaustive. A *mismatch* always fails.
"""

from __future__ import annotations

import argparse
import os
import sys

from web3 import Web3

from langchain_uniswap_v2.abis import erc20_abi, router_abi
from langchain_uniswap_v2.networks import KNOWN_NETWORKS

RPC_ENV_PREFIX = "UNISWAP_V2_RPC_"
RPC_TIMEOUT_SECS = 20

OK = "OK"
SKIP = "SKIP"
FAIL = "FAIL"


def resolve_rpc_url(chain_id: int, entry: dict) -> str | None:
    """The endpoint to use for this chain: the UNISWAP_V2_RPC_<chain_id>
    override if set, otherwise the registry's own public default."""
    return os.environ.get(f"{RPC_ENV_PREFIX}{chain_id}") or entry.get("rpc_url")


def same_address(left: str | None, right: str | None) -> bool:
    return (
        left is not None
        and right is not None
        and Web3.to_checksum_address(left) == Web3.to_checksum_address(right)
    )


def verify_chain(chain_id: int, entry: dict) -> tuple[str, list[str]]:
    """Returns (status, lines) for one registry entry. Status is OK, SKIP
    (endpoint unreachable -- nothing could be checked) or FAIL."""
    lines: list[str] = []
    rpc_url = resolve_rpc_url(chain_id, entry)
    if rpc_url is None:
        return SKIP, [f"no rpc_url registered and no {RPC_ENV_PREFIX}{chain_id} set"]

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": RPC_TIMEOUT_SECS}))
    try:
        if not w3.is_connected():
            return SKIP, [f"unreachable: {rpc_url}"]
    except Exception as err:  # any transport error is a skip, not a failure
        return SKIP, [f"unreachable: {rpc_url} ({type(err).__name__}: {err})"]

    problems: list[str] = []

    # An RPC that answers but serves a different chain would make every
    # address check below meaningless, so confirm the chain first.
    try:
        reported_chain_id = w3.eth.chain_id
    except Exception as err:
        return SKIP, [f"eth_chainId failed on {rpc_url} ({type(err).__name__}: {err})"]
    if reported_chain_id != chain_id:
        problems.append(f"endpoint reports chain_id {reported_chain_id}, expected {chain_id}")

    router_address = Web3.to_checksum_address(entry["router"])
    try:
        if w3.eth.get_code(router_address) in (b"", "0x", None):
            problems.append(f"router {router_address} has no bytecode on this chain")
            return FAIL, problems
    except Exception as err:
        return SKIP, [f"eth_getCode failed ({type(err).__name__}: {err})"]

    router = w3.eth.contract(address=router_address, abi=router_abi)

    try:
        on_chain_factory = router.functions.factory().call()
    except Exception as err:
        problems.append(f"router.factory() call failed ({type(err).__name__}: {err})")
        on_chain_factory = None
    if on_chain_factory is not None and not same_address(on_chain_factory, entry["factory"]):
        problems.append(
            f"factory mismatch: table has {entry['factory']}, "
            f"router.factory() returns {on_chain_factory}"
        )

    try:
        on_chain_weth = router.functions.WETH().call()
    except Exception as err:
        problems.append(f"router.WETH() call failed ({type(err).__name__}: {err})")
        return FAIL, problems

    configured = entry["native_wrapped"]
    if configured is None:
        problems.append(f"native_wrapped is None -- router.WETH() returns {on_chain_weth}")
    elif not same_address(configured, on_chain_weth):
        problems.append(
            f"native_wrapped mismatch: table has {configured}, "
            f"router.WETH() returns {on_chain_weth}"
        )

    token = w3.eth.contract(address=Web3.to_checksum_address(on_chain_weth), abi=erc20_abi)
    try:
        symbol = token.functions.symbol().call()
        decimals = token.functions.decimals().call()
        detail = f"{on_chain_weth} ({symbol}, {decimals} decimals)"
    except Exception as err:  # informational only, never fatal
        detail = f"{on_chain_weth} (symbol/decimals unreadable: {type(err).__name__})"

    lines.append(f"router.WETH() = {detail}")
    if problems:
        return FAIL, problems + lines
    return OK, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="treat an unreachable endpoint as a failure instead of a skip",
    )
    parser.add_argument(
        "--chain",
        type=int,
        action="append",
        dest="chains",
        help="verify only this chain_id (repeatable); default is every entry",
    )
    args = parser.parse_args()

    chain_ids = sorted(args.chains) if args.chains else sorted(KNOWN_NETWORKS)
    unknown = [cid for cid in chain_ids if cid not in KNOWN_NETWORKS]
    if unknown:
        print(f"Not in KNOWN_NETWORKS: {unknown}", file=sys.stderr)
        return 2

    statuses: dict[str, list[int]] = {OK: [], SKIP: [], FAIL: []}
    for chain_id in chain_ids:
        entry = KNOWN_NETWORKS[chain_id]
        status, lines = verify_chain(chain_id, entry)
        statuses[status].append(chain_id)
        print(f"[{status:4}] {chain_id} {entry['name']}")
        for line in lines:
            print(f"         {line}")

    print()
    print(
        f"{len(statuses[OK])} ok, {len(statuses[FAIL])} failed, "
        f"{len(statuses[SKIP])} skipped, of {len(chain_ids)} checked"
    )
    if statuses[FAIL]:
        print(f"FAILED: {statuses[FAIL]}")
    if statuses[SKIP]:
        print(f"SKIPPED (unreachable, not verified): {statuses[SKIP]}")

    if statuses[FAIL]:
        return 1
    if statuses[SKIP] and args.require_all:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
