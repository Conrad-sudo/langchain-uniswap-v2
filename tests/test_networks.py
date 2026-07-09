"""
Structural sanity checks on the KNOWN_NETWORKS chain registry. These are pure
data-shape checks -- no network calls -- and exist to catch the exact class
of mistake documented in summary.md #6 (e.g. a ticker string accidentally
stored where an address is required, which would crash Web3.to_checksum_address
at construction time).
"""

import re

import pytest
from web3 import Web3

from langchain_uniswap_v2.networks import KNOWN_NETWORKS

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

REQUIRED_KEYS = {
    "name",
    "rpc_url",
    "router",
    "factory",
    "native_wrapped",
    "native_token",
}


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_entry_has_all_required_keys(chain_id):
    assert set(KNOWN_NETWORKS[chain_id]) == REQUIRED_KEYS


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_router_and_factory_are_valid_addresses(chain_id):
    entry = KNOWN_NETWORKS[chain_id]
    for field in ("router", "factory"):
        address = entry[field]
        assert isinstance(address, str), f"{field} on chain {chain_id} is not a string"
        assert ADDRESS_RE.match(address), (
            f"{field} on chain {chain_id} is not a valid address: {address}"
        )
        Web3.to_checksum_address(address)  # must not raise


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_native_wrapped_is_a_valid_address_or_none(chain_id):
    native_wrapped = KNOWN_NETWORKS[chain_id]["native_wrapped"]
    if native_wrapped is None:
        return
    assert isinstance(native_wrapped, str)
    assert ADDRESS_RE.match(native_wrapped), (
        f"native_wrapped on chain {chain_id} is not a valid address: {native_wrapped}"
    )
    Web3.to_checksum_address(native_wrapped)  # must not raise


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_native_token_is_a_non_empty_ticker_not_an_address(chain_id):
    native_token = KNOWN_NETWORKS[chain_id]["native_token"]
    assert isinstance(native_token, str) and native_token
    assert not ADDRESS_RE.match(native_token), (
        f"native_token on chain {chain_id} looks like an address, not a ticker: {native_token}"
    )


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_rpc_url_is_a_string_or_none(chain_id):
    rpc_url = KNOWN_NETWORKS[chain_id]["rpc_url"]
    assert rpc_url is None or (isinstance(rpc_url, str) and rpc_url.startswith("http"))


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_name_is_a_non_empty_string(chain_id):
    name = KNOWN_NETWORKS[chain_id]["name"]
    assert isinstance(name, str) and name


def test_chain_ids_are_ints():
    assert all(isinstance(chain_id, int) for chain_id in KNOWN_NETWORKS)


def test_names_are_unique():
    names = [entry["name"] for entry in KNOWN_NETWORKS.values()]
    assert len(names) == len(set(names))
