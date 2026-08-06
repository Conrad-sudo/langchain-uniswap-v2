"""
Test-only address constants and the Web3Env mock-contract registry, kept out
of conftest.py so test modules can `from web3_mocks import ...` without
colliding with the repo-root conftest.py module name.
"""

from unittest.mock import MagicMock

from web3 import Web3 as RealWeb3

from langchain_uniswap_v2.abis import erc20_abi, factory_abi, pair_abi, router_abi

ROUTER = "0x" + "11" * 20
FACTORY = "0x" + "22" * 20
NATIVE_WRAPPED = "0x" + "33" * 20
TOKEN_A = "0x" + "44" * 20
TOKEN_B = "0x" + "55" * 20
TOKEN_C = "0x" + "88" * 20
PAIR = "0x" + "66" * 20
OWNER = "0x" + "77" * 20
ZERO_ADDRESS = "0x" + "00" * 20


class Web3Env:
    """Handle returned by the mock_web3 fixture for configuring contracts."""

    def __init__(self, mock_w3_cls, w3_instance):
        self.mock_w3_cls = mock_w3_cls
        self.w3 = w3_instance
        self._contracts: dict[tuple[str, int], MagicMock] = {}

    def _contract_side_effect(self, address, abi):
        key = (address, id(abi))
        if key not in self._contracts:
            mock = MagicMock(name=f"contract[{address}]")
            # Real Contract objects always expose .address -- _call() reads
            # it directly (contract.address), unlike the balance/decimals
            # calls elsewhere that go through .functions.
            mock.address = address
            self._contracts[key] = mock
        return self._contracts[key]

    def contract_for(self, address: str, abi: list) -> MagicMock:
        """Get (or create) the mock contract that will be returned for this
        (address, abi) pair, so it can be configured before construction."""
        checksummed = RealWeb3.to_checksum_address(address)
        return self._contract_side_effect(checksummed, abi)

    @property
    def router(self) -> MagicMock:
        return self.contract_for(ROUTER, router_abi)

    @property
    def factory(self) -> MagicMock:
        return self.contract_for(FACTORY, factory_abi)

    def erc20(self, address: str) -> MagicMock:
        return self.contract_for(address, erc20_abi)

    def pair(self, address: str = PAIR) -> MagicMock:
        return self.contract_for(address, pair_abi)
