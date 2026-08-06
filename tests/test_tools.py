"""
Tests for the 5 LangChain tools returned by UniswapV2Toolkit.get_tools().
Contract calls are mocked (see conftest.py / web3_mocks.py) -- these assert
on the toolkit's own arithmetic/routing logic, not on real on-chain values.
"""

import time

import pytest
from langchain_core.tools import ToolException
from web3.exceptions import ContractLogicError

import langchain_uniswap_v2.toolkit as uvt
from tests.web3_mocks import (
    FACTORY,
    NATIVE_WRAPPED,
    OWNER,
    PAIR,
    ROUTER,
    TOKEN_A,
    TOKEN_B,
    TOKEN_C,
    ZERO_ADDRESS,
)


@pytest.fixture
def tools(toolkit):
    by_name = {t.name: t for t in toolkit.get_tools()}
    assert set(by_name) == {
        "get_quote_in",
        "get_quote_out",
        "get_pool_quote",
        "get_lp_amounts",
        "get_liquidity_token_balance",
        "is_token_balance_sufficient",
        "is_native_balance_sufficient",
        "is_derived_token_input_sufficient",
        "is_derived_native_input_sufficient",
        "is_liquidity_sufficient",
        "is_liquidity_sufficient_eth",
        "is_liquidity_removal_sufficient",
        "approve_token",
        "swap_exact_tokens_for_tokens",
        "swap_tokens_for_exact_tokens",
        "swap_exact_eth_for_tokens",
        "swap_eth_for_exact_tokens",
        "swap_exact_tokens_for_eth",
        "swap_tokens_for_exact_eth",
        "add_liquidity",
        "add_liquidity_eth",
        "remove_liquidity",
        "remove_liquidity_eth",
    }
    return by_name


def test_get_quote_out_computes_from_router_amounts(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 6
    # path routes through NATIVE_WRAPPED since toolkit fixture configures it
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]

    result = tools["get_quote_out"].invoke(
        {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_in": 1}
    )

    assert result["amount_in"] == 1
    assert result["amount_out"] == 2.5
    assert result["path"][0].lower() == TOKEN_A.lower()
    assert result["path"][-1].lower() == TOKEN_B.lower()
    assert len(result["path"]) == 3  # routed through native_wrapped


def test_get_quote_out_raises_tool_exception_on_no_liquidity(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsOut.return_value.call.side_effect = (
        ContractLogicError("execution reverted")
    )

    with pytest.raises(ToolException):
        tools["get_quote_out"].invoke(
            {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_in": 1}
        )


def test_get_quote_in_computes_from_router_amounts(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
        10**18,
    ]

    result = tools["get_quote_in"].invoke(
        {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_out": 1}
    )

    assert result["amount_in"] == 3.0
    assert result["amount_out"] == 1


def test_get_quote_in_raises_tool_exception_on_no_liquidity(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.side_effect = ContractLogicError(
        "execution reverted"
    )

    with pytest.raises(ToolException):
        tools["get_quote_in"].invoke(
            {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_out": 1}
        )


def _configure_pair(mock_web3, token_a=TOKEN_A, token_b=TOKEN_B, pair_address=PAIR):
    mock_web3.factory.functions.getPair.return_value.call.return_value = pair_address
    pair = mock_web3.pair(pair_address)
    pair.functions.token0.return_value.call.return_value = token_a
    return pair


def test_get_pool_quote_uses_live_reserves_and_router_quote(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18

    result = tools["get_pool_quote"].invoke(
        {"token_a": TOKEN_A, "token_b": TOKEN_B, "amount_a": 1}
    )

    assert result["amount_a"] == 1
    assert result["amount_b_desired"] == 2.0
    # reserve_a/reserve_b passed to quote() should follow token0 ordering
    mock_web3.router.functions.quote.assert_called_once()
    call_args = mock_web3.router.functions.quote.call_args[0]
    assert call_args[1:] == (1000, 2000)


def test_get_pool_quote_swaps_reserves_when_token_a_is_token1(mock_web3, toolkit, tools):
    # token0 in the pair is token_b, not token_a
    pair = _configure_pair(mock_web3, token_a=TOKEN_B)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.quote.return_value.call.return_value = 1

    tools["get_pool_quote"].invoke({"token_a": TOKEN_A, "token_b": TOKEN_B, "amount_a": 1})

    call_args = mock_web3.router.functions.quote.call_args[0]
    assert call_args[1:] == (2000, 1000)


def test_get_lp_amounts_proportional_redemption(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18

    result = tools["get_lp_amounts"].invoke(
        {"token_a": TOKEN_A, "token_b": TOKEN_B, "lp_amount": 10 / 10**18}
    )

    # 10 units of liquidity (in base units of a totalSupply=100) -> 10% share
    assert result["expected_a"] == pytest.approx(100 / 10**18)
    assert result["expected_b"] == pytest.approx(200 / 10**18)


def test_get_liquidity_token_balance(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 5 * 10**18

    result = tools["get_liquidity_token_balance"].invoke(
        {"owner_address": OWNER, "token_a": TOKEN_A, "token_b": TOKEN_B}
    )

    assert result == 5.0
    pair.functions.balanceOf.assert_called_once()


def test_pair_raises_tool_exception_when_no_pool_exists(mock_web3, toolkit, tools):
    mock_web3.factory.functions.getPair.return_value.call.return_value = ZERO_ADDRESS

    with pytest.raises(ToolException):
        tools["get_liquidity_token_balance"].invoke(
            {"owner_address": OWNER, "token_a": TOKEN_A, "token_b": TOKEN_B}
        )


def test_pair_lookup_is_cached(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 0

    tools["get_liquidity_token_balance"].invoke(
        {"owner_address": OWNER, "token_a": TOKEN_A, "token_b": TOKEN_B}
    )
    tools["get_liquidity_token_balance"].invoke(
        {"owner_address": OWNER, "token_a": TOKEN_A, "token_b": TOKEN_B}
    )

    mock_web3.factory.functions.getPair.assert_called_once()


def test_pair_lookup_is_order_independent(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 0

    tools["get_liquidity_token_balance"].invoke(
        {"owner_address": OWNER, "token_a": TOKEN_A, "token_b": TOKEN_B}
    )
    tools["get_liquidity_token_balance"].invoke(
        {"owner_address": OWNER, "token_a": TOKEN_B, "token_b": TOKEN_A}
    )

    mock_web3.factory.functions.getPair.assert_called_once()


def test_is_token_balance_sufficient_true_and_false(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**18

    assert (
        tools["is_token_balance_sufficient"].invoke(
            {"token_address": TOKEN_A, "amount": 1, "owner_address": OWNER}
        )
        is True
    )
    assert (
        tools["is_token_balance_sufficient"].invoke(
            {"token_address": TOKEN_A, "amount": 1.5, "owner_address": OWNER}
        )
        is False
    )


def test_is_native_balance_sufficient_true_and_false(mock_web3, toolkit, tools):
    mock_web3.w3.eth.get_balance.return_value = 10**18

    assert (
        tools["is_native_balance_sufficient"].invoke({"amount": 1, "owner_address": OWNER})
        is True
    )
    assert (
        tools["is_native_balance_sufficient"].invoke({"amount": 1.5, "owner_address": OWNER})
        is False
    )
    call_args = mock_web3.w3.eth.get_balance.call_args[0]
    assert call_args[0].lower() == OWNER.lower()


def test_is_derived_token_input_sufficient(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
        10**18,
    ]
    required_base = 3 * 10**18 * 10050 // 10000
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = required_base

    result = tools["is_derived_token_input_sufficient"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_out": 1,
            "owner_address": OWNER,
        }
    )

    assert result["is_sufficient"] is True
    assert result["required_input"] == required_base / 10**18

    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = (
        required_base - 1
    )
    result = tools["is_derived_token_input_sufficient"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_out": 1,
            "owner_address": OWNER,
        }
    )
    assert result["is_sufficient"] is False


def test_is_derived_native_input_sufficient(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        2 * 10**18,
        10**18,
    ]
    required_base = 2 * 10**18 * 10050 // 10000
    mock_web3.w3.eth.get_balance.return_value = required_base

    result = tools["is_derived_native_input_sufficient"].invoke(
        {"token_out": TOKEN_B, "amount_out": 1, "owner_address": OWNER}
    )

    assert result["is_sufficient"] is True
    assert result["required_input"] == required_base / 10**18


def test_is_liquidity_sufficient(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 2 * 10**18

    result = tools["is_liquidity_sufficient"].invoke(
        {"token_a": TOKEN_A, "amount_a": 1, "token_b": TOKEN_B, "owner_address": OWNER}
    )
    assert result["is_sufficient"] is True
    assert result["required_b"] == 2.0

    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**18 - 1
    result = tools["is_liquidity_sufficient"].invoke(
        {"token_a": TOKEN_A, "amount_a": 1, "token_b": TOKEN_B, "owner_address": OWNER}
    )
    assert result["is_sufficient"] is False


def test_is_liquidity_sufficient_eth(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3, token_a=TOKEN_A)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.quote.return_value.call.return_value = 3 * 10**18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**18
    mock_web3.w3.eth.get_balance.return_value = 3 * 10**18

    result = tools["is_liquidity_sufficient_eth"].invoke(
        {"token": TOKEN_A, "amount_token": 1, "owner_address": OWNER}
    )
    assert result["is_sufficient"] is True
    assert result["required_native"] == 3.0


def test_is_liquidity_removal_sufficient(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 5 * 10**18

    assert (
        tools["is_liquidity_removal_sufficient"].invoke(
            {"token_a": TOKEN_A, "token_b": TOKEN_B, "lp_amount": 5, "owner_address": OWNER}
        )
        is True
    )
    assert (
        tools["is_liquidity_removal_sufficient"].invoke(
            {"token_a": TOKEN_A, "token_b": TOKEN_B, "lp_amount": 5.1, "owner_address": OWNER}
        )
        is False
    )


def test_approve_token_builds_unsigned_tx(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xabc"
    mock_web3.w3.eth.get_transaction_count.return_value = 7
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["approve_token"].invoke(
        {
            "token_address": TOKEN_A,
            "spender_address": ROUTER,
            "amount": 100,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve"]
    assert plan["calls"][0]["to"] == TOKEN_A
    assert plan["calls"][0]["data"] == "0xabc"
    mock_web3.erc20(TOKEN_A).encode_abi.assert_called_once_with(
        abi_element_identifier="approve", args=[ROUTER, 100 * 10**18]
    )
    tx = plan["transactions"][-1]
    assert tx["nonce"] == 7
    assert tx["chainId"] == 1
    mock_web3.w3.eth.get_transaction_count.assert_called_once_with(OWNER, "pending")


def test_approve_token_respects_explicit_nonce(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xabc"
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["approve_token"].invoke(
        {
            "token_address": TOKEN_A,
            "spender_address": ROUTER,
            "amount": 1,
            "from_address": OWNER,
            "nonce": 42,
        }
    )

    mock_web3.w3.eth.get_transaction_count.assert_not_called()
    assert plan["transactions"][-1]["nonce"] == 42


def test_approve_token_raises_tool_exception_when_build_would_revert(
    mock_web3, toolkit, tools
):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xabc"
    mock_web3.w3.eth.get_transaction_count.return_value = 0
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.side_effect = ContractLogicError("execution reverted")

    with pytest.raises(ToolException):
        tools["approve_token"].invoke(
            {
                "token_address": TOKEN_A,
                "spender_address": ROUTER,
                "amount": 1,
                "from_address": OWNER,
            }
        )


def test_approve_token_unlimited_approves_max_uint256(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xabc"
    mock_web3.w3.eth.get_transaction_count.return_value = 0
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["approve_token"].invoke(
        {
            "token_address": TOKEN_A,
            "spender_address": ROUTER,
            "from_address": OWNER,
            "unlimited": True,
        }
    )

    mock_web3.erc20(TOKEN_A).encode_abi.assert_called_once_with(
        abi_element_identifier="approve", args=[ROUTER, 2**256 - 1]
    )
    # unlimited=True skips the decimals lookup -- there's no whole-unit
    # amount to scale.
    mock_web3.erc20(TOKEN_A).functions.decimals.assert_not_called()
    assert plan["summary"]["unlimited"] is True
    assert plan["summary"]["amount"] is None


def test_swap_exact_tokens_for_tokens_builds_unsigned_tx(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_transaction_count.return_value = 3
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    before = int(time.time())
    plan = tools["swap_exact_tokens_for_tokens"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_in": 1,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]
    mock_web3.router.encode_abi.assert_called_once()
    amount_in_arg, amount_out_min_arg, path_arg, to_arg, deadline_arg = (
        mock_web3.router.encode_abi.call_args.kwargs["args"]
    )
    assert amount_in_arg == 10**18
    assert amount_out_min_arg == 2_500_000 * 9950 // 10000
    assert path_arg[0].lower() == TOKEN_A.lower()
    assert path_arg[-1].lower() == TOKEN_B.lower()
    assert to_arg.lower() == OWNER.lower()
    assert deadline_arg >= before + 600
    action_tx = plan["transactions"][-1]
    assert action_tx["value"] == 0
    assert action_tx["nonce"] == 4  # approve takes base nonce 3, swap takes 4
    mock_web3.w3.eth.get_transaction_count.assert_called_once_with(OWNER, "pending")


def test_swap_exact_tokens_for_tokens_raises_on_no_liquidity(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.router.functions.getAmountsOut.return_value.call.side_effect = (
        ContractLogicError("execution reverted")
    )

    with pytest.raises(ToolException):
        tools["swap_exact_tokens_for_tokens"].invoke(
            {
                "token_in": TOKEN_A,
                "token_out": TOKEN_B,
                "amount_in": 1,
                "from_address": OWNER,
            }
        )


def test_swap_exact_tokens_for_tokens_preflight_raises_when_balance_insufficient(
    mock_web3, toolkit, tools
):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**18 - 1

    with pytest.raises(ToolException, match="short by"):
        tools["swap_exact_tokens_for_tokens"].invoke(
            {
                "token_in": TOKEN_A,
                "token_out": TOKEN_B,
                "amount_in": 1,
                "from_address": OWNER,
            }
        )
    # Preflight fails before any quote is attempted.
    mock_web3.router.functions.getAmountsOut.assert_not_called()


def test_preflight_false_skips_the_balance_check(mock_web3):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 0
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        native_wrapped_address=NATIVE_WRAPPED,
        preflight=False,
    )
    tools = {t.name: t for t in toolkit.get_tools()}

    plan = tools["swap_exact_tokens_for_tokens"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_in": 1,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]


def test_swap_tokens_for_exact_tokens_builds_unsigned_tx(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xbeef"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["swap_tokens_for_exact_tokens"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_out": 1,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]
    amount_out_arg, amount_in_max_arg, _path_arg, to_arg, _deadline = (
        mock_web3.router.encode_abi.call_args.kwargs["args"]
    )
    assert amount_out_arg == 10**18
    assert amount_in_max_arg == 3 * 10**18 * 10050 // 10000
    assert to_arg.lower() == OWNER.lower()


def test_swap_exact_eth_for_tokens_sets_value(mock_web3, toolkit, tools):
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        2_000_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["swap_exact_eth_for_tokens"].invoke(
        {"token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["swap"]
    assert plan["calls"][0]["value"] == 10**18
    amount_out_min_arg, path_arg, to_arg, _deadline = (
        mock_web3.router.encode_abi.call_args.kwargs["args"]
    )
    assert amount_out_min_arg == 2_000_000 * 9950 // 10000
    assert path_arg[0].lower() == NATIVE_WRAPPED.lower()
    assert path_arg[-1].lower() == TOKEN_B.lower()
    assert plan["transactions"][-1]["value"] == 10**18


def test_swap_eth_for_exact_tokens_sets_value_to_amount_in_max(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        2 * 10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["swap_eth_for_exact_tokens"].invoke(
        {"token_out": TOKEN_B, "amount_out": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["swap"]
    assert plan["calls"][0]["value"] == 2 * 10**18 * 10050 // 10000
    assert plan["transactions"][-1]["value"] == 2 * 10**18 * 10050 // 10000


def test_swap_exact_tokens_for_eth_no_value_sent(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["swap_exact_tokens_for_eth"].invoke(
        {"token_in": TOKEN_A, "amount_in": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]
    path_arg = mock_web3.router.encode_abi.call_args.kwargs["args"][2]
    assert path_arg[-1].lower() == NATIVE_WRAPPED.lower()
    assert plan["calls"][-1]["value"] == 0


def test_swap_tokens_for_exact_eth_no_value_sent(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xdead"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["swap_tokens_for_exact_eth"].invoke(
        {"token_in": TOKEN_A, "amount_out": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]
    assert plan["calls"][-1]["value"] == 0


def test_add_liquidity_builds_unsigned_tx(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove_a"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_B).encode_abi.return_value = "0xapprove_b"
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliq"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["add_liquidity"].invoke(
        {"token_a": TOKEN_A, "token_b": TOKEN_B, "amount_a": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "approve", "add_liquidity"]
    (
        _token_a_arg,
        _token_b_arg,
        amount_a_desired_arg,
        amount_b_desired_arg,
        amount_a_min_arg,
        amount_b_min_arg,
        to_arg,
        _deadline,
    ) = mock_web3.router.encode_abi.call_args.kwargs["args"]
    assert amount_a_desired_arg == 10**18
    assert amount_b_desired_arg == 2 * 10**18
    assert amount_a_min_arg == 10**18 * 9950 // 10000
    assert amount_b_min_arg == 2 * 10**18 * 9950 // 10000
    assert to_arg.lower() == OWNER.lower()


def test_add_liquidity_eth_sets_value_to_derived_eth_amount(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3, token_a=TOKEN_A)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.router.functions.quote.return_value.call.return_value = 3 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliqeth"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["add_liquidity_eth"].invoke(
        {"token": TOKEN_A, "amount_token": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "add_liquidity"]
    (
        _token_arg,
        amount_token_desired_arg,
        _amount_token_min_arg,
        amount_eth_min_arg,
        to_arg,
        _deadline,
    ) = mock_web3.router.encode_abi.call_args.kwargs["args"]
    assert amount_token_desired_arg == 10**18
    assert amount_eth_min_arg == 3 * 10**18 * 9950 // 10000
    assert to_arg.lower() == OWNER.lower()
    assert plan["calls"][-1]["value"] == 3 * 10**18
    assert plan["transactions"][-1]["value"] == 3 * 10**18


def test_remove_liquidity_builds_unsigned_tx(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 10**30
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    pair.encode_abi.return_value = "0xapprove_lp"
    mock_web3.router.encode_abi.return_value = "0xremoveliq"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["remove_liquidity"].invoke(
        {
            "token_a": TOKEN_A,
            "token_b": TOKEN_B,
            "lp_amount": 10 / 10**18,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "remove_liquidity"]
    (
        _token_a_arg,
        _token_b_arg,
        liquidity_arg,
        amount_a_min_arg,
        amount_b_min_arg,
        to_arg,
        _deadline,
    ) = mock_web3.router.encode_abi.call_args.kwargs["args"]
    assert liquidity_arg == 10
    # raw0 = 10*1000//100 = 100, raw1 = 10*2000//100 = 200; token0 == TOKEN_A
    assert amount_a_min_arg == 100 * 9950 // 10000
    assert amount_b_min_arg == 200 * 9950 // 10000
    assert to_arg.lower() == OWNER.lower()


def test_remove_liquidity_eth_builds_unsigned_tx(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3, token_a=TOKEN_A)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 10**30
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    pair.encode_abi.return_value = "0xapprove_lp"
    mock_web3.router.encode_abi.return_value = "0xremoveliqeth"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["remove_liquidity_eth"].invoke(
        {"token": TOKEN_A, "lp_amount": 10 / 10**18, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "remove_liquidity"]
    (
        _token_arg,
        liquidity_arg,
        amount_token_min_arg,
        amount_eth_min_arg,
        to_arg,
        _deadline,
    ) = mock_web3.router.encode_abi.call_args.kwargs["args"]
    assert liquidity_arg == 10
    assert amount_token_min_arg == 100 * 9950 // 10000
    assert amount_eth_min_arg == 200 * 9950 // 10000
    assert to_arg.lower() == OWNER.lower()


@pytest.mark.parametrize(
    "tool_name, kwargs",
    [
        (
            "swap_exact_eth_for_tokens",
            {"token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER},
        ),
        (
            "swap_eth_for_exact_tokens",
            {"token_out": TOKEN_B, "amount_out": 1, "from_address": OWNER},
        ),
        (
            "swap_exact_tokens_for_eth",
            {"token_in": TOKEN_A, "amount_in": 1, "from_address": OWNER},
        ),
        (
            "swap_tokens_for_exact_eth",
            {"token_in": TOKEN_A, "amount_out": 1, "from_address": OWNER},
        ),
        (
            "add_liquidity_eth",
            {"token": TOKEN_A, "amount_token": 1, "from_address": OWNER},
        ),
        (
            "remove_liquidity_eth",
            {"token": TOKEN_A, "lp_amount": 1, "from_address": OWNER},
        ),
        (
            "is_derived_native_input_sufficient",
            {"token_out": TOKEN_B, "amount_out": 1, "owner_address": OWNER},
        ),
        (
            "is_liquidity_sufficient_eth",
            {"token": TOKEN_A, "amount_token": 1, "owner_address": OWNER},
        ),
    ],
)
def test_native_asset_tools_require_native_wrapped_address(mock_web3, tool_name, kwargs):
    no_native_toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc", router_address=ROUTER, factory_address=FACTORY
    )
    tools = {t.name: t for t in no_native_toolkit.get_tools()}

    with pytest.raises(ToolException, match="native_wrapped_address"):
        tools[tool_name].invoke(kwargs)


# ---- v0.3.0 execution-plan behavior: the core fix, calls mode, approval
# composition per tool, nonce sequencing, and recipient override. ----


@pytest.fixture
def reset_tools(mock_web3):
    """Tools bound to a toolkit with reset_residual_approvals explicitly
    enabled, so approval-composition tests can check the trailing
    approve_reset call appears (or is correctly never appended) regardless
    of tx_mode's default."""
    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        native_wrapped_address=NATIVE_WRAPPED,
        reset_residual_approvals=True,
    )
    return {t.name: t for t in toolkit.get_tools()}


def test_write_tools_build_when_allowance_is_not_standing(mock_web3, toolkit, tools):
    """The core v0.3.0 fix: the action call cannot be simulated before the
    approval in the same plan is mined, so its gas estimate reverts. The
    plan must still build -- falling back to a static gas limit for that
    call -- instead of raising, which is exactly what broke every
    allowance-dependent write tool pre-v0.3.0."""
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_transaction_count.return_value = 0
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.side_effect = [
        60_000,  # approve estimates fine
        ContractLogicError("execution reverted: TransferHelper::transferFrom"),
    ]

    plan = tools["swap_exact_tokens_for_tokens"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_in": 1,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]
    approve_tx, swap_tx = plan["transactions"]
    assert approve_tx["gas"] == int(60_000 * toolkit.gas_buffer)
    assert approve_tx["gas_estimated"] is True
    assert swap_tx["gas"] == uvt.DEFAULT_GAS["swap"]
    assert swap_tx["gas_estimated"] is False


def test_calls_mode_write_tool_makes_no_nonce_gas_or_fee_requests(mock_web3):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove_a"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_B).encode_abi.return_value = "0xapprove_b"
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliq"

    toolkit = uvt.UniswapV2Toolkit(
        rpc_url="http://fake-rpc",
        router_address=ROUTER,
        factory_address=FACTORY,
        native_wrapped_address=NATIVE_WRAPPED,
        tx_mode="calls",
    )
    tools = {t.name: t for t in toolkit.get_tools()}

    plan = tools["add_liquidity"].invoke(
        {"token_a": TOKEN_A, "token_b": TOKEN_B, "amount_a": 1, "from_address": OWNER}
    )

    assert plan["transactions"] is None
    # calls mode defaults reset_residual_approvals to True.
    assert [c["role"] for c in plan["calls"]] == [
        "approve",
        "approve",
        "add_liquidity",
        "approve_reset",
        "approve_reset",
    ]
    mock_web3.w3.eth.get_transaction_count.assert_not_called()
    mock_web3.w3.eth.estimate_gas.assert_not_called()
    mock_web3.w3.eth.get_block.assert_not_called()


def test_add_liquidity_explicit_nonce_increments_across_calls(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove_a"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_B).encode_abi.return_value = "0xapprove_b"
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliq"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    plan = tools["add_liquidity"].invoke(
        {
            "token_a": TOKEN_A,
            "token_b": TOKEN_B,
            "amount_a": 1,
            "from_address": OWNER,
            "nonce": 100,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "approve", "add_liquidity"]
    assert [tx["nonce"] for tx in plan["transactions"]] == [100, 101, 102]
    mock_web3.w3.eth.get_transaction_count.assert_not_called()


def test_swap_exact_eth_for_tokens_first_call_revert_is_fatal(mock_web3, toolkit, tools):
    """A single-call plan (no leading approval) has no earlier call to
    excuse a failed estimate -- the revert must still surface."""
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        2_000_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.w3.eth.get_transaction_count.return_value = 0
    mock_web3.w3.eth.chain_id = 1
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.side_effect = ContractLogicError("execution reverted")

    with pytest.raises(ToolException):
        tools["swap_exact_eth_for_tokens"].invoke(
            {"token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER}
        )


# ---- approval composition per write tool, matching package_update.md's
# §4.5 table: exact-pull tools never reset even with the flag on; tools
# that may pull less than approved reset only when the flag is on; tools
# that send native value need no approval at all. ----


def test_swap_exact_tokens_for_tokens_never_resets_even_when_enabled(mock_web3, reset_tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"

    plan = reset_tools["swap_exact_tokens_for_tokens"].invoke(
        {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]


def test_swap_tokens_for_exact_tokens_resets_residual_approval_when_enabled(
    mock_web3, reset_tools
):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"

    plan = reset_tools["swap_tokens_for_exact_tokens"].invoke(
        {"token_in": TOKEN_A, "token_out": TOKEN_B, "amount_out": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap", "approve_reset"]
    assert mock_web3.erc20(TOKEN_A).encode_abi.call_args_list[-1].kwargs["args"] == [ROUTER, 0]


def test_swap_exact_eth_for_tokens_never_needs_approval(mock_web3, reset_tools):
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        2_000_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_balance.return_value = 10**30

    plan = reset_tools["swap_exact_eth_for_tokens"].invoke(
        {"token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["swap"]


def test_swap_eth_for_exact_tokens_never_needs_approval(mock_web3, reset_tools):
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        2 * 10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_balance.return_value = 10**30

    plan = reset_tools["swap_eth_for_exact_tokens"].invoke(
        {"token_out": TOKEN_B, "amount_out": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["swap"]


def test_swap_exact_tokens_for_eth_never_resets_even_when_enabled(mock_web3, reset_tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"

    plan = reset_tools["swap_exact_tokens_for_eth"].invoke(
        {"token_in": TOKEN_A, "amount_in": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap"]


def test_swap_tokens_for_exact_eth_resets_residual_approval_when_enabled(
    mock_web3, reset_tools
):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsIn.return_value.call.return_value = [
        3 * 10**18,
        10**18,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"

    plan = reset_tools["swap_tokens_for_exact_eth"].invoke(
        {"token_in": TOKEN_A, "amount_out": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "swap", "approve_reset"]
    assert mock_web3.erc20(TOKEN_A).encode_abi.call_args_list[-1].kwargs["args"] == [ROUTER, 0]


def test_add_liquidity_resets_both_residual_approvals_when_enabled(mock_web3, reset_tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove_a"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_B).encode_abi.return_value = "0xapprove_b"
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliq"

    plan = reset_tools["add_liquidity"].invoke(
        {"token_a": TOKEN_A, "token_b": TOKEN_B, "amount_a": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == [
        "approve",
        "approve",
        "add_liquidity",
        "approve_reset",
        "approve_reset",
    ]
    assert mock_web3.erc20(TOKEN_A).encode_abi.call_args_list[-1].kwargs["args"] == [ROUTER, 0]
    assert mock_web3.erc20(TOKEN_B).encode_abi.call_args_list[-1].kwargs["args"] == [ROUTER, 0]


def test_add_liquidity_eth_resets_residual_approval_when_enabled(mock_web3, reset_tools):
    pair = _configure_pair(mock_web3, token_a=TOKEN_A)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.router.functions.quote.return_value.call.return_value = 3 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliqeth"

    plan = reset_tools["add_liquidity_eth"].invoke(
        {"token": TOKEN_A, "amount_token": 1, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "add_liquidity", "approve_reset"]
    assert mock_web3.erc20(TOKEN_A).encode_abi.call_args_list[-1].kwargs["args"] == [ROUTER, 0]


def test_remove_liquidity_never_resets_even_when_enabled(mock_web3, reset_tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 10**30
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    pair.encode_abi.return_value = "0xapprove_lp"
    mock_web3.router.encode_abi.return_value = "0xremoveliq"

    plan = reset_tools["remove_liquidity"].invoke(
        {
            "token_a": TOKEN_A,
            "token_b": TOKEN_B,
            "lp_amount": 10 / 10**18,
            "from_address": OWNER,
        }
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "remove_liquidity"]


def test_remove_liquidity_eth_never_resets_even_when_enabled(mock_web3, reset_tools):
    pair = _configure_pair(mock_web3, token_a=TOKEN_A)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 10**30
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    pair.encode_abi.return_value = "0xapprove_lp"
    mock_web3.router.encode_abi.return_value = "0xremoveliqeth"

    plan = reset_tools["remove_liquidity_eth"].invoke(
        {"token": TOKEN_A, "lp_amount": 10 / 10**18, "from_address": OWNER}
    )

    assert [c["role"] for c in plan["calls"]] == ["approve", "remove_liquidity"]


# ---- recipient override, on a representative tool from each structural
# category (plain token swap, native-value swap, liquidity add, liquidity
# remove) -- the override logic (Web3.to_checksum_address(recipient or
# from_address)) is identical across all ten swap/liquidity tools. ----


def test_swap_exact_tokens_for_tokens_recipient_overrides_router_to(mock_web3, toolkit, tools):
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove"
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        5 * 10**17,
        2_500_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    tools["swap_exact_tokens_for_tokens"].invoke(
        {
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount_in": 1,
            "from_address": OWNER,
            "recipient": TOKEN_C,
        }
    )

    to_arg = mock_web3.router.encode_abi.call_args.kwargs["args"][3]
    assert to_arg.lower() == TOKEN_C.lower()


def test_swap_exact_eth_for_tokens_recipient_overrides_router_to(mock_web3, toolkit, tools):
    mock_web3.router.functions.getAmountsOut.return_value.call.return_value = [
        10**18,
        2_000_000,
    ]
    mock_web3.router.encode_abi.return_value = "0xswap"
    mock_web3.w3.eth.get_balance.return_value = 10**30
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    tools["swap_exact_eth_for_tokens"].invoke(
        {"token_out": TOKEN_B, "amount_in": 1, "from_address": OWNER, "recipient": TOKEN_C}
    )

    to_arg = mock_web3.router.encode_abi.call_args.kwargs["args"][2]
    assert to_arg.lower() == TOKEN_C.lower()


def test_add_liquidity_recipient_overrides_router_to(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    mock_web3.erc20(TOKEN_A).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_A).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_A).encode_abi.return_value = "0xapprove_a"
    mock_web3.erc20(TOKEN_B).functions.decimals.return_value.call.return_value = 18
    mock_web3.erc20(TOKEN_B).functions.balanceOf.return_value.call.return_value = 10**30
    mock_web3.erc20(TOKEN_B).encode_abi.return_value = "0xapprove_b"
    mock_web3.router.functions.quote.return_value.call.return_value = 2 * 10**18
    mock_web3.router.encode_abi.return_value = "0xaddliq"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    tools["add_liquidity"].invoke(
        {
            "token_a": TOKEN_A,
            "token_b": TOKEN_B,
            "amount_a": 1,
            "from_address": OWNER,
            "recipient": TOKEN_C,
        }
    )

    to_arg = mock_web3.router.encode_abi.call_args.kwargs["args"][6]
    assert to_arg.lower() == TOKEN_C.lower()


def test_remove_liquidity_recipient_overrides_router_to(mock_web3, toolkit, tools):
    pair = _configure_pair(mock_web3)
    pair.functions.decimals.return_value.call.return_value = 18
    pair.functions.balanceOf.return_value.call.return_value = 10**30
    pair.functions.getReserves.return_value.call.return_value = (1000, 2000, 0)
    pair.functions.totalSupply.return_value.call.return_value = 100
    pair.encode_abi.return_value = "0xapprove_lp"
    mock_web3.router.encode_abi.return_value = "0xremoveliq"
    mock_web3.w3.eth.get_block.return_value = {}
    mock_web3.w3.eth.gas_price = 1
    mock_web3.w3.eth.estimate_gas.return_value = 21_000

    tools["remove_liquidity"].invoke(
        {
            "token_a": TOKEN_A,
            "token_b": TOKEN_B,
            "lp_amount": 10 / 10**18,
            "from_address": OWNER,
            "recipient": TOKEN_C,
        }
    )

    to_arg = mock_web3.router.encode_abi.call_args.kwargs["args"][5]
    assert to_arg.lower() == TOKEN_C.lower()
