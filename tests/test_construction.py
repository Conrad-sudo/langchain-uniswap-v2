import pytest
from langchain_core.tools import ToolException
from web3 import Web3 as RealWeb3
from web3.exceptions import ContractLogicError, MismatchedABI

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


def test_constructor_reset_residual_approvals_defaults_false_in_eoa_mode(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )
    assert toolkit.reset_residual_approvals is False


def test_constructor_reset_residual_approvals_defaults_true_in_calls_mode(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        tx_mode="calls",
    )
    assert toolkit.reset_residual_approvals is True


def test_constructor_reset_residual_approvals_explicit_override_wins(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        tx_mode="calls",
        reset_residual_approvals=False,
    )
    assert toolkit.reset_residual_approvals is False


def test_constructor_preflight_defaults_true(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )
    assert toolkit.preflight is True


def test_constructor_preflight_can_be_disabled(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        preflight=False,
    )
    assert toolkit.preflight is False


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


def test_for_chain_passes_kwargs_through_to_constructor(mock_web3, monkeypatch):
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
    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999, tx_mode="calls", preflight=False)
    assert toolkit.tx_mode == "calls"
    assert toolkit.preflight is False


@pytest.fixture
def registry_entry(monkeypatch):
    """Registers chain 999 in KNOWN_NETWORKS for the duration of a test."""
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


# The registry supplies router/factory/native_wrapped, but a caller must be
# able to override any of them -- for a stale entry, or a fork reusing a chain
# id. Passing them explicitly *and* splatting **kwargs used to raise
# TypeError("got multiple values for keyword argument"), closing that door.


def test_for_chain_native_wrapped_address_override(mock_web3, registry_entry):
    override = "0x" + "99" * 20

    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999, native_wrapped_address=override)

    assert toolkit.native_wrapped_address == RealWeb3.to_checksum_address(override)


def test_for_chain_router_address_override(mock_web3, registry_entry):
    override = "0x" + "aa" * 20

    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999, router_address=override)

    assert toolkit.router.address == RealWeb3.to_checksum_address(override)


def test_for_chain_factory_address_override(mock_web3, registry_entry):
    override = "0x" + "bb" * 20

    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999, factory_address=override)

    assert toolkit.factory.address == RealWeb3.to_checksum_address(override)


def test_for_chain_all_three_addresses_overridden_at_once(mock_web3, registry_entry):
    router, factory, wrapped = "0x" + "aa" * 20, "0x" + "bb" * 20, "0x" + "99" * 20

    toolkit = uvt.UniswapV2Toolkit.for_chain(
        chain_id=999,
        router_address=router,
        factory_address=factory,
        native_wrapped_address=wrapped,
    )

    assert toolkit.router.address == RealWeb3.to_checksum_address(router)
    assert toolkit.factory.address == RealWeb3.to_checksum_address(factory)
    assert toolkit.native_wrapped_address == RealWeb3.to_checksum_address(wrapped)


def test_for_chain_without_overrides_still_uses_registry_values(mock_web3, registry_entry):
    """setdefault must not change behaviour for callers passing no override."""
    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=999)

    assert toolkit.router.address == RealWeb3.to_checksum_address(ROUTER)
    assert toolkit.factory.address == RealWeb3.to_checksum_address(FACTORY)
    assert toolkit.native_wrapped_address == RealWeb3.to_checksum_address(NATIVE_WRAPPED)


@pytest.mark.parametrize("chain_id", list(KNOWN_NETWORKS))
def test_for_chain_configures_native_wrapped_for_every_known_chain(mock_web3, chain_id):
    """Every registry entry must produce a toolkit that can build native-asset
    swaps -- a None native_wrapped leaves eight tools registered but raising."""
    toolkit = uvt.UniswapV2Toolkit.for_chain(chain_id=chain_id)

    assert toolkit.native_wrapped_address is not None


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


def checksummed(*addresses: str) -> list[str]:
    return [RealWeb3.to_checksum_address(address) for address in addresses]


DIRECT = (TOKEN_A, TOKEN_B)
HOPPED = (TOKEN_A, NATIVE_WRAPPED, TOKEN_B)


def test_candidate_paths_direct_only_when_no_native_wrapped_configured(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )

    assert toolkit._candidate_paths(TOKEN_A, TOKEN_B) == [checksummed(*DIRECT)]


def test_candidate_paths_offers_direct_first_then_the_hop(toolkit):
    """Direct must come first: an exact tie is kept by the earlier candidate,
    and one pool beats two for the same output."""
    assert toolkit._candidate_paths(TOKEN_A, TOKEN_B) == [
        checksummed(*DIRECT),
        checksummed(*HOPPED),
    ]


def test_candidate_paths_direct_only_when_token_in_is_native_wrapped(toolkit):
    assert toolkit._candidate_paths(NATIVE_WRAPPED, TOKEN_B) == [
        checksummed(NATIVE_WRAPPED, TOKEN_B)
    ]


def test_candidate_paths_direct_only_when_token_out_is_native_wrapped(toolkit):
    assert toolkit._candidate_paths(TOKEN_A, NATIVE_WRAPPED) == [
        checksummed(TOKEN_A, NATIVE_WRAPPED)
    ]


def test_route_out_prefers_the_hop_when_a_dust_direct_pair_quotes_worse(mock_web3, toolkit):
    """The regression test for the dust-pool bug: the direct pair exists and
    holds non-zero reserves -- enough for the old boolean check to select it
    -- but returns 34% less than the wrapped-native route. Numbers are the
    measured Avalanche USDC->USDT case, in 6-decimal base units."""
    mock_web3.set_amounts_out(
        {DIRECT: [1_000_000, 495_672], HOPPED: [1_000_000, 10**16, 750_485]}
    )

    path, amounts = toolkit._route_out(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*HOPPED)
    assert amounts[-1] == 750_485


def test_route_out_keeps_the_direct_pair_when_it_quotes_better(mock_web3, toolkit):
    mock_web3.set_amounts_out(
        {DIRECT: [1_000_000, 998_000], HOPPED: [1_000_000, 10**16, 750_485]}
    )

    path, amounts = toolkit._route_out(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*DIRECT)
    assert amounts[-1] == 998_000


def test_route_out_breaks_an_exact_tie_towards_the_direct_pair(mock_web3, toolkit):
    """Same output either way -- take the single hop: less gas, and less that
    can move between quoting and execution."""
    mock_web3.set_amounts_out(
        {DIRECT: [1_000_000, 900_000], HOPPED: [1_000_000, 10**16, 900_000]}
    )

    path, _amounts = toolkit._route_out(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*DIRECT)


def test_route_out_falls_back_to_the_hop_when_no_direct_pair_exists(mock_web3, toolkit):
    mock_web3.set_amounts_out({HOPPED: [1_000_000, 10**16, 750_485]})

    path, _amounts = toolkit._route_out(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*HOPPED)


def test_route_out_raises_the_usual_exception_when_every_candidate_reverts(mock_web3, toolkit):
    mock_web3.set_amounts_out({})

    with pytest.raises(ToolException, match="No Uniswap V2 liquidity path found"):
        toolkit._route_out(1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT")


def test_route_in_prefers_the_path_needing_the_least_input(mock_web3, toolkit):
    """Exact-output is the mirror image: lower amounts[0] wins."""
    mock_web3.set_amounts_in(
        {DIRECT: [2_000_000, 1_000_000], HOPPED: [1_330_000, 10**16, 1_000_000]}
    )

    path, amounts = toolkit._route_in(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*HOPPED)
    assert amounts[0] == 1_330_000


def test_route_in_breaks_an_exact_tie_towards_the_direct_pair(mock_web3, toolkit):
    mock_web3.set_amounts_in(
        {DIRECT: [1_005_000, 1_000_000], HOPPED: [1_005_000, 10**16, 1_000_000]}
    )

    path, _amounts = toolkit._route_in(
        1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT"
    )

    assert path == checksummed(*DIRECT)


def test_route_in_raises_the_usual_exception_when_every_candidate_reverts(mock_web3, toolkit):
    mock_web3.set_amounts_in({})

    with pytest.raises(ToolException, match="No Uniswap V2 liquidity path found"):
        toolkit._route_in(1_000_000, TOKEN_A, TOKEN_B, label_in="USDC", label_out="USDT")


def test_call_builds_account_agnostic_call_via_pure_encoding(mock_web3, toolkit):
    erc20 = mock_web3.erc20(TOKEN_A)
    erc20.address = RealWeb3.to_checksum_address(TOKEN_A)
    erc20.encode_abi.return_value = "0xabc123"

    call = toolkit._call(
        erc20,
        "approve",
        [ROUTER, 100],
        value=0,
        role="approve",
        description="Approve router to spend 100",
    )

    assert call == {
        "to": RealWeb3.to_checksum_address(TOKEN_A),
        "value": 0,
        "data": "0xabc123",
        "role": "approve",
        "description": "Approve router to spend 100",
    }
    erc20.encode_abi.assert_called_once_with(
        abi_element_identifier="approve", args=[ROUTER, 100]
    )
    # Pure ABI encoding -- must never touch the network.
    mock_web3.w3.eth.get_transaction_count.assert_not_called()
    mock_web3.w3.eth.estimate_gas.assert_not_called()
    assert erc20.functions.mock_calls == []


def test_call_wraps_encoder_errors_in_tool_exception(mock_web3, toolkit):
    erc20 = mock_web3.erc20(TOKEN_A)
    erc20.address = RealWeb3.to_checksum_address(TOKEN_A)
    erc20.encode_abi.side_effect = MismatchedABI("value not compatible with type uint256")

    with pytest.raises(ToolException):
        toolkit._call(
            erc20,
            "approve",
            [ROUTER, 2**300],
            role="approve",
            description="Approve router to spend an out-of-range amount",
        )


def test_default_gas_uses_module_constant_by_role(toolkit):
    assert toolkit._default_gas({"role": "swap"}) == uvt.DEFAULT_GAS["swap"]


def test_default_gas_respects_constructor_override(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        default_gas={"swap": 999_999},
    )
    assert toolkit._default_gas({"role": "swap"}) == 999_999
    # Unrelated roles still fall back to the module default.
    assert toolkit._default_gas({"role": "approve"}) == uvt.DEFAULT_GAS["approve"]


def test_fee_params_eip1559_when_base_fee_present(mock_web3, toolkit):
    mock_web3.w3.eth.get_block.return_value = {"baseFeePerGas": 1000}
    mock_web3.w3.eth.max_priority_fee = 2

    fees = toolkit._fee_params()

    assert fees == {"maxFeePerGas": 1000 * 2 + 2, "maxPriorityFeePerGas": 2}
    mock_web3.w3.eth.get_block.assert_called_once_with("latest")


def test_fee_params_legacy_when_no_base_fee(mock_web3, toolkit):
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 42

    fees = toolkit._fee_params()

    assert fees == {"gasPrice": 42}


def test_gas_for_uses_default_when_estimate_gas_disabled(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        estimate_gas=False,
    )
    call = {"to": ROUTER, "value": 0, "data": "0xdead", "role": "swap"}

    gas, estimated = toolkit._gas_for(call, ROUTER, has_pending_prerequisite=False)

    assert gas == uvt.DEFAULT_GAS["swap"]
    assert estimated is False
    mock_web3.w3.eth.estimate_gas.assert_not_called()


def test_gas_for_uses_live_estimate_with_buffer(mock_web3, toolkit):
    mock_web3.w3.eth.estimate_gas.return_value = 100_000
    call = {"to": ROUTER, "value": 0, "data": "0xdead", "role": "swap"}

    gas, estimated = toolkit._gas_for(call, ROUTER, has_pending_prerequisite=False)

    assert gas == int(100_000 * toolkit.gas_buffer)
    assert estimated is True


def test_gas_for_falls_back_when_prerequisite_pending(mock_web3, toolkit):
    mock_web3.w3.eth.estimate_gas.side_effect = ContractLogicError("execution reverted")
    call = {"to": ROUTER, "value": 0, "data": "0xdead", "role": "swap"}

    gas, estimated = toolkit._gas_for(call, ROUTER, has_pending_prerequisite=True)

    assert gas == uvt.DEFAULT_GAS["swap"]
    assert estimated is False


def test_gas_for_raises_when_first_call_reverts(mock_web3, toolkit):
    mock_web3.w3.eth.estimate_gas.side_effect = ContractLogicError("execution reverted")
    call = {"to": ROUTER, "value": 0, "data": "0xdead", "role": "swap"}

    with pytest.raises(ToolException):
        toolkit._gas_for(call, ROUTER, has_pending_prerequisite=False)


def test_render_eoa_assigns_sequential_nonces_and_shared_fees(mock_web3, toolkit):
    mock_web3.w3.eth.get_transaction_count.return_value = 5
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {"baseFeePerGas": 100}
    mock_web3.w3.eth.max_priority_fee = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    calls = [
        {"to": TOKEN_A, "value": 0, "data": "0x1", "role": "approve"},
        {"to": ROUTER, "value": 0, "data": "0x2", "role": "swap"},
    ]
    txs, estimated = toolkit._render_eoa(calls, TOKEN_A)

    assert [tx["nonce"] for tx in txs] == [5, 6]
    assert all(tx["chainId"] == 1 for tx in txs)
    assert all(tx["maxFeePerGas"] == 201 for tx in txs)  # 100*2 + 1, shared across both
    assert estimated == [True, True]
    mock_web3.w3.eth.get_transaction_count.assert_called_once_with(
        RealWeb3.to_checksum_address(TOKEN_A), "pending"
    )


def test_render_eoa_respects_explicit_starting_nonce(mock_web3, toolkit):
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    calls = [
        {"to": TOKEN_A, "value": 0, "data": "0x1", "role": "approve"},
        {"to": ROUTER, "value": 0, "data": "0x2", "role": "swap"},
    ]
    txs, _ = toolkit._render_eoa(calls, TOKEN_A, nonce=42)

    assert [tx["nonce"] for tx in txs] == [42, 43]
    mock_web3.w3.eth.get_transaction_count.assert_not_called()


def test_render_eoa_emits_no_field_a_transaction_does_not_have(mock_web3, toolkit):
    """The rendered dict has to be signable exactly as returned.

    eth_account validates the dict it is handed and raises `TypeError: Unknown
    kwargs` on anything it does not recognise, so a single piece of metadata
    tucked in beside the real fields breaks the first thing every EOA consumer
    does. `gas_estimated` used to live here and did exactly that; it travels
    alongside now.
    """
    mock_web3.w3.eth.get_transaction_count.return_value = 5
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {"baseFeePerGas": 100}
    mock_web3.w3.eth.max_priority_fee = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    calls = [{"to": ROUTER, "value": 0, "data": "0x1", "role": "swap"}]
    txs, estimated = toolkit._render_eoa(calls, TOKEN_A)

    assert set(txs[0]) == {
        "from",
        "to",
        "value",
        "data",
        "nonce",
        "chainId",
        "gas",
        "maxFeePerGas",
        "maxPriorityFeePerGas",
    }
    assert estimated == [True]


def test_eth_account_signs_the_rendered_dict_exactly_as_returned(mock_web3, toolkit):
    """The README's flow, run for real rather than asserted about."""
    from eth_account import Account

    mock_web3.w3.eth.get_transaction_count.return_value = 5
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {"baseFeePerGas": 100}
    mock_web3.w3.eth.max_priority_fee = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    account = Account.from_key("0x" + "11" * 32)
    calls = [{"to": ROUTER, "value": 0, "data": "0x1", "role": "swap"}]
    txs, _ = toolkit._render_eoa(calls, account.address)

    signed = account.sign_transaction(txs[0])
    assert signed.raw_transaction


def test_plan_renders_transactions_in_eoa_mode(mock_web3, toolkit):
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000
    mock_web3.w3.eth.chain_id = 1

    calls = [{"to": ROUTER, "value": 0, "data": "0x1", "role": "swap"}]
    plan = toolkit._plan(calls, from_address=TOKEN_A, summary={"amount": 1})

    assert plan["calls"] is calls
    assert plan["chain_id"] == 1
    assert plan["summary"] == {"amount": 1}
    assert len(plan["transactions"]) == 1


def test_plan_carries_gas_provenance_beside_the_transactions(mock_web3, toolkit):
    mock_web3.w3.eth.get_transaction_count.return_value = 5
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {"baseFeePerGas": 100}
    mock_web3.w3.eth.max_priority_fee = 1
    mock_web3.w3.eth.estimate_gas.side_effect = [
        21_000,
        ContractLogicError("execution reverted"),
    ]

    calls = [
        {"to": TOKEN_A, "value": 0, "data": "0x1", "role": "approve"},
        {"to": ROUTER, "value": 0, "data": "0x2", "role": "swap"},
    ]
    plan = toolkit._plan(calls, from_address=TOKEN_A, summary={})

    assert plan["gas_estimated"] == [True, False]
    assert len(plan["gas_estimated"]) == len(plan["transactions"])


def test_plan_calls_mode_makes_no_eoa_rpc_calls(mock_web3):
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        tx_mode="calls",
    )
    calls = [{"to": ROUTER, "value": 0, "data": "0x1", "role": "swap"}]

    plan = toolkit._plan(calls, from_address=TOKEN_A, summary={})

    assert plan["calls"] is calls
    assert plan["transactions"] is None
    # Nothing was estimated, so claiming [] or [False] would both be untrue.
    assert plan["gas_estimated"] is None
    mock_web3.w3.eth.get_transaction_count.assert_not_called()
    mock_web3.w3.eth.estimate_gas.assert_not_called()
