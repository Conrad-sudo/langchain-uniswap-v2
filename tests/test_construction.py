import pytest
from web3 import Web3 as RealWeb3

import langchain_uniswap_v2.toolkit as uvt
from langchain_uniswap_v2.networks import KNOWN_NETWORKS
from tests.web3_mocks import FACTORY, NATIVE_WRAPPED, ROUTER, TOKEN_A, TOKEN_B


def test_constructor_raises_when_rpc_not_connected(mock_web3):
    mock_web3.w3.is_connected.return_value = False
    with pytest.raises(ConnectionError):
        uvt.UniswapV2Toolkit(rpc_url="http://dead-rpc", router_address=ROUTER)


def test_constructor_binds_router_and_explicit_factory(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
    )
    assert toolkit.router is mock_web3.router
    assert toolkit.factory is mock_web3.factory
    # factory() should never be called on the router when an explicit
    # factory address was supplied.
    mock_web3.router.functions.factory.assert_not_called()


def test_constructor_derives_factory_from_router_when_omitted(mock_web3):
    mock_web3.router.functions.factory.return_value.call.return_value = FACTORY
    toolkit = uvt.UniswapV2Toolkit(rpc_url="http://fake-rpc", router_address=ROUTER)
    mock_web3.router.functions.factory.return_value.call.assert_called_once()
    assert toolkit.factory is mock_web3.factory


def test_constructor_native_wrapped_address_none_by_default(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )
    assert toolkit.native_wrapped_address is None


def test_constructor_native_wrapped_address_must_be_valid_address(mock_web3):
    with pytest.raises(ValueError):
        uvt.UniswapV2Toolkit(
            rpc_url="http://fake-rpc",
            router_address=ROUTER,
            factory_address=FACTORY,
            native_wrapped_address="ETH",  # ticker, not an address -- must reject
        )


def test_constructor_checksums_native_wrapped_address(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        native_wrapped_address=NATIVE_WRAPPED.lower(),
    )
    assert toolkit.native_wrapped_address == RealWeb3.to_checksum_address(NATIVE_WRAPPED)


def test_for_chain_unknown_chain_id_raises(mock_web3):
    with pytest.raises(ValueError, match="No known Uniswap V2 deployment"):
        uvt.UniswapV2Toolkit.for_chain(chain_id=99999999)


def test_for_chain_no_rpc_url_available_raises(mock_web3, monkeypatch):
    monkeypatch.setitem(
        KNOWN_NETWORKS,
        999,
        {
            "name": "test-chain",
            "rpc_url": None,
            "router": ROUTER,
            "factory": FACTORY,
            "native_wrapped": None,
            "native_token": "TEST",
        },
    )
    with pytest.raises(ValueError, match="No public rpc_url is known"):
        uvt.UniswapV2Toolkit.for_chain(chain_id=999)


def test_for_chain_builds_toolkit_from_registry(mock_web3, monkeypatch):
    monkeypatch.setitem(
        KNOWN_NETWORKS,
        999,
        {
            "name": "test-chain",
            "rpc_url": "http://registry-rpc",
            "router": ROUTER,
            "factory": FACTORY,
            "native_wrapped": NATIVE_WRAPPED,
            "native_token": "TEST",
        },
    )
    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999)
    mock_web3.mock_w3_cls.HTTPProvider.assert_any_call("http://registry-rpc")
    assert toolkit.native_wrapped_address == RealWeb3.to_checksum_address(NATIVE_WRAPPED)


def test_for_chain_rpc_url_override_takes_priority(mock_web3, monkeypatch):
    monkeypatch.setitem(
        KNOWN_NETWORKS,
        999,
        {
            "name": "test-chain",
            "rpc_url": "http://registry-rpc",
            "router": ROUTER,
            "factory": FACTORY,
            "native_wrapped": None,
            "native_token": "TEST",
        },
    )
    uvt.UniswapV2Toolkit.for_chain(chain_id=999, rpc_url="http://override-rpc")
    mock_web3.mock_w3_cls.HTTPProvider.assert_any_call("http://override-rpc")


@pytest.mark.parametrize(
    "amount, decimals, expected",
    [
        (1, 18, 10**18),
        (1.5, 18, 1_500_000_000_000_000_000),
        (100, 6, 100_000_000),
        (0.000001, 6, 1),
    ],
)
def test_to_base_units(amount, decimals, expected):
    assert uvt.UniswapV2Toolkit._to_base_units(amount, decimals) == expected


def test_build_path_direct_when_no_native_wrapped_configured(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )

    path = toolkit._build_path(TOKEN_A, TOKEN_B)
    assert path == [
        RealWeb3.to_checksum_address(TOKEN_A),
        RealWeb3.to_checksum_address(TOKEN_B),
    ]


def test_build_path_routes_through_native_wrapped(toolkit):

    path = toolkit._build_path(TOKEN_A, TOKEN_B)
    assert path == [
        RealWeb3.to_checksum_address(TOKEN_A),
        RealWeb3.to_checksum_address(NATIVE_WRAPPED),
        RealWeb3.to_checksum_address(TOKEN_B),
    ]


def test_build_path_direct_when_token_in_is_native_wrapped(toolkit):

    path = toolkit._build_path(NATIVE_WRAPPED, TOKEN_B)
    assert path == [
        RealWeb3.to_checksum_address(NATIVE_WRAPPED),
        RealWeb3.to_checksum_address(TOKEN_B),
    ]


def test_build_path_direct_when_token_out_is_native_wrapped(toolkit):

    path = toolkit._build_path(TOKEN_A, NATIVE_WRAPPED)
    assert path == [
        RealWeb3.to_checksum_address(TOKEN_A),
        RealWeb3.to_checksum_address(NATIVE_WRAPPED),
    ]
