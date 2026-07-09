"""
Tests for the 5 LangChain tools returned by UniswapV2Toolkit.get_tools().
Contract calls are mocked (see conftest.py / web3_mocks.py) -- these assert
on the toolkit's own arithmetic/routing logic, not on real on-chain values.
"""

import pytest
from langchain_core.tools import ToolException
from web3.exceptions import ContractLogicError

from tests.web3_mocks import OWNER, PAIR, TOKEN_A, TOKEN_B, ZERO_ADDRESS


@pytest.fixture
def tools(toolkit):
    by_name = {t.name: t for t in toolkit.get_tools()}
    assert set(by_name) == {
        "get_quote_in",
        "get_quote_out",
        "get_pool_quote",
        "get_lp_amounts",
        "get_liquidity_token_balance",
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
