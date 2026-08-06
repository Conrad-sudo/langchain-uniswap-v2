"""
Shared fixtures for mocking web3 so tests never make real network calls.

Strategy: replace the `Web3` name inside the `langchain_uniswap_v2.toolkit` module with
a MagicMock, but keep the real `Web3.to_checksum_address` static method so
address validation/formatting behaves exactly as it would in production.
`w3.eth.contract(address=..., abi=...)` is wired to return one distinct
MagicMock per (address, abi-identity) pair -- calling it again with the same
arguments returns the same mock (mirroring the toolkit's own
_erc20_cache/_pair_cache), so tests can configure a contract's return values
either before or after the toolkit is constructed.
"""

from unittest.mock import MagicMock

import pytest
from web3 import Web3 as RealWeb3

import langchain_uniswap_v2.toolkit as uvt
from tests.web3_mocks import FACTORY, NATIVE_WRAPPED, ROUTER, ZERO_ADDRESS, Web3Env


@pytest.fixture
def mock_web3(monkeypatch):
    mock_w3_cls = MagicMock(name="Web3")
    mock_w3_cls.to_checksum_address.side_effect = RealWeb3.to_checksum_address
    mock_w3_cls.HTTPProvider.return_value = "fake-provider"

    w3_instance = MagicMock(name="w3")
    w3_instance.is_connected.return_value = True
    mock_w3_cls.return_value = w3_instance

    env = Web3Env(mock_w3_cls, w3_instance)
    w3_instance.eth.contract.side_effect = env._contract_side_effect
    # _build_path calls factory.getPair to check for a direct pair before
    # falling back to a wrapped-native hop. Default to "no direct pair" so
    # existing tests that never configured this keep routing through
    # native_wrapped as before; a test exercising the direct-pair path sets
    # env.factory.functions.getPair(...).call.return_value explicitly.
    env.factory.functions.getPair.return_value.call.return_value = ZERO_ADDRESS

    monkeypatch.setattr(uvt, "Web3", mock_w3_cls)
    return env


@pytest.fixture
def toolkit(mock_web3):
    """A UniswapV2Toolkit built against ROUTER/FACTORY/NATIVE_WRAPPED, with
    factory address passed explicitly (so router.functions.factory() is never
    called unless a test wants to exercise that auto-derivation path)."""
    return uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        native_wrapped_address=NATIVE_WRAPPED,
    )
