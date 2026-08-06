"""
Standalone LangChain toolkit for Uniswap V2 (and V2-fork, e.g. PancakeSwap)
queries plus execution plans for writes -- ready for an EOA to sign or a
smart-contract wallet to batch.


Example (explicit addresses, any Uniswap V2-shaped DEX on any chain):
    from langchain_uniswap_v2 import UniswapV2Toolkit

    toolkit = UniswapV2Toolkit(
        rpc_url="https://eth.llamarpc.com",
        router_address="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        native_wrapped_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
    )
    tools = toolkit.get_tools()

Example (known chain, just pass a chain_id):
    toolkit = UniswapV2Toolkit.for_chain(chain_id=1)
    tools = toolkit.get_tools()
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Literal

from langchain_core.tools import ToolException, tool
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError, MismatchedABI

from .abis import erc20_abi, factory_abi, pair_abi, router_abi
from .networks import KNOWN_NETWORKS

# Basis-point denominator for slippage math (e.g. 50 bps = 0.5%).
BPS_DENOMINATOR = 10_000
DEFAULT_SLIPPAGE_BPS = 50
DEFAULT_SWAP_DEADLINE_SECS = 600

# Static gas-limit fallback per call role, used when a call's gas can't be
# estimated yet (e.g. it depends on an earlier, not-yet-mined call in the
# same plan). Override per-instance via the constructor's default_gas param.
DEFAULT_GAS = {
    "approve": 70_000,
    "approve_reset": 50_000,
    "swap": 300_000,
    "add_liquidity": 350_000,
    "remove_liquidity": 300_000,
}


class UniswapV2Toolkit:
    """
    Bind once to an RPC endpoint, router, and (optionally) factory/native-wrapped
    token, then call get_tools() to get LangChain tools scoped to that
    deployment. All tool arguments are plain contract addresses and amounts --
    no ticker registry or wallet state is required.

    get_tools() returns two kinds of tools:

    - Read-only tools that only make RPC calls: quote/preview tools
      (get_quote_in, get_quote_out, get_pool_quote, get_lp_amounts,
      get_liquidity_token_balance) plus balance-sufficiency checks
      (is_token_balance_sufficient, is_native_balance_sufficient,
      is_derived_token_input_sufficient, is_derived_native_input_sufficient,
      is_liquidity_sufficient, is_liquidity_sufficient_eth,
      is_liquidity_removal_sufficient) that answer "does this address hold
      enough" before a write tool would be called, given an explicit
      owner_address -- no wallet state involved, just a balance read.
    - Write tools (approve_token, the six swap_* tools, and
      add_liquidity/add_liquidity_eth/remove_liquidity/remove_liquidity_eth)
      that build and return an execution *plan* -- an ordered list of
      account-agnostic calls (any required approval, then the action, then
      an approval reset where needed), plus the same calls rendered as
      unsigned EOA transactions when tx_mode="eoa" (the default). No write
      tool ever holds a private key, signs anything, or submits anything to
      the network. This toolkit intentionally has no concept of a signer or
      wallet: the same instance works identically for an agent driving a
      local eth_account key, a KMS-backed signer, or a smart-contract
      wallet, because it never needs to know which one it's talking to.

    Every write tool includes its own approval call(s) in the plan
    automatically, sized to what that call actually needs -- approve_token
    remains available for explicit/manual approvals outside of any swap or
    deposit flow. tx_mode="calls" (see the constructor) returns plans with
    calls only and makes zero nonce/gas/fee RPC calls, for a
    smart-contract wallet's own batch executor. All amount-based write
    tools also take slippage_bps (basis points, default 50) and derive
    amountOutMin/amountInMax/*Min from a live on-chain quote, and
    deadline_secs (default 600) for the plan's on-chain expiry -- both are
    always explicit tool arguments, never silently omitted.
    """

    def __init__(
        self,
        rpc_url: str,
        router_address: str,
        factory_address: str | None = None,
        native_wrapped_address: str | None = None,
        *,
        tx_mode: Literal["eoa", "calls"] = "eoa",
        estimate_gas: bool = True,
        gas_buffer: float = 1.25,
        default_gas: dict[str, int] | None = None,
        reset_residual_approvals: bool | None = None,
        preflight: bool = True,
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Could not connect to RPC endpoint: {rpc_url}")

        self.router: Contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_address),
            abi=router_abi,
        )
        resolved_factory_address: str = (
            factory_address or self.router.functions.factory().call()
        )
        self.factory: Contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(resolved_factory_address),
            abi=factory_abi,
        )
        # When set, quotes between two non-wrapped-native tokens are routed
        # through this token (mirrors how Uniswap V2 pools are usually seeded).
        self.native_wrapped_address = (
            Web3.to_checksum_address(native_wrapped_address)
            if native_wrapped_address
            else None
        )

        # "eoa": write tools also render signable transactions (nonce, gas,
        # fees). "calls": write tools return only the account-agnostic calls
        # list -- zero nonce/gas/fee RPC calls -- for a smart-contract
        # wallet's own batch executor.
        self.tx_mode = tx_mode
        self.estimate_gas = estimate_gas
        self.gas_buffer = gas_buffer
        self.default_gas = {**DEFAULT_GAS, **(default_gas or {})}

        # Whether an approve-then-act call sequence appends a trailing
        # approve(spender, 0) after actions that may pull less than they
        # were approved for. An EOA pays gas for that extra transaction, so
        # it defaults to off; a batching account pays nothing extra for it
        # (and some enforce it), so it defaults to on -- unless the caller
        # states a preference explicitly.
        self.reset_residual_approvals = (
            reset_residual_approvals
            if reset_residual_approvals is not None
            else (tx_mode == "calls")
        )
        # Whether write tools run their matching balance/allowance-independent
        # sufficiency check before building, raising ToolException if it
        # fails -- replaces the safety net eth_estimateGas used to provide
        # by accident before plans could be built ahead of a standing
        # allowance.
        self.preflight = preflight

        self._erc20_abi = erc20_abi
        self._pair_abi = pair_abi
        self._erc20_cache: dict[str, Contract] = {}
        self._pair_cache: dict[tuple[str, str], Contract] = {}

    @classmethod
    def for_chain(
        cls, chain_id: int, rpc_url: str | None = None, **kwargs
    ) -> UniswapV2Toolkit:
        """
        Convenience constructor for chains in KNOWN_NETWORKS -- looks up the
        router, factory, and native-wrapped-token addresses for chain_id so
        callers only need to supply a chain_id.

        Args:
            chain_id: The EVM chain ID (e.g. 1 for Ethereum mainnet, 56 for BSC).
            rpc_url: Optional RPC endpoint override. If omitted, falls back to
                KNOWN_NETWORKS' public endpoint for that chain -- fine for
                prototyping, but rate-limited; pass your own for production.
            **kwargs: Passed through to the main constructor (e.g. tx_mode,
                estimate_gas, gas_buffer, default_gas, reset_residual_approvals,
                preflight).

        Raises:
            ValueError: If chain_id has no entry in KNOWN_NETWORKS, or if
                neither rpc_url nor KNOWN_NETWORKS has one for this chain.
                Use the main constructor with explicit addresses/RPC for any
                other chain.
        """
        network = KNOWN_NETWORKS.get(chain_id)
        if network is None:
            raise ValueError(
                f"No known Uniswap V2 deployment registered for chain_id "
                f"{chain_id}. Known chain_ids: {sorted(KNOWN_NETWORKS)}. For "
                f"any other chain, instantiate UniswapV2Toolkit(...) directly "
                f"with explicit addresses."
            )
        resolved_rpc_url = rpc_url or network["rpc_url"]
        if resolved_rpc_url is None:
            raise ValueError(
                f"No public rpc_url is known for chain_id {chain_id} "
                f"('{network['name']}'). Pass rpc_url explicitly: "
                f"UniswapV2Toolkit.for_chain({chain_id}, rpc_url=...)."
            )
        return cls(
            rpc_url=resolved_rpc_url,
            router_address=network["router"],
            factory_address=network["factory"],
            native_wrapped_address=network["native_wrapped"],
            **kwargs,
        )

    # ---- internal helpers (not exposed as tools) ----

    def _erc20(self, address: str) -> Contract:
        address = Web3.to_checksum_address(address)
        if address not in self._erc20_cache:
            self._erc20_cache[address] = self.w3.eth.contract(
                address=address, abi=self._erc20_abi
            )
        return self._erc20_cache[address]

    def _decimals(self, address: str) -> int:
        return self._erc20(address).functions.decimals().call()

    @staticmethod
    def _to_base_units(amount: float, decimals: int) -> int:
        return int(Decimal(str(amount)) * Decimal(10) ** decimals)

    def _pair(self, token_a: str, token_b: str) -> Contract:
        a, b = Web3.to_checksum_address(token_a), Web3.to_checksum_address(token_b)
        key = (a, b) if a < b else (b, a)
        if key not in self._pair_cache:
            pair_address = self.factory.functions.getPair(a, b).call()
            if int(pair_address, 16) == 0:
                raise ToolException(f"No Uniswap V2 pair exists for {a} / {b}.")
            self._pair_cache[key] = self.w3.eth.contract(
                address=pair_address, abi=self._pair_abi
            )
        return self._pair_cache[key]

    def _quote_deposit_base(self, token_a: str, token_b: str, amount_a_base: int) -> int:
        """Proportional token_b amount (base units) to match amount_a_base,
        via live pool reserves and the router's quote()."""
        pair = self._pair(token_a, token_b)
        reserve0, reserve1, _ = pair.functions.getReserves().call()
        token0 = pair.functions.token0().call()
        if token0.lower() == Web3.to_checksum_address(token_a).lower():
            reserve_a, reserve_b = reserve0, reserve1
        else:
            reserve_a, reserve_b = reserve1, reserve0
        return self.router.functions.quote(amount_a_base, reserve_a, reserve_b).call()

    @staticmethod
    def _lp_redemption_base(
        pair: Contract, token_a: str, liquidity_base: int
    ) -> tuple[int, int]:
        """Expected (token_a, token_b) return (base units) for burning
        liquidity_base LP tokens, via the proportional share formula.

        Note: if the factory's protocol fee is on, totalSupply grows at burn
        time (a fee mint happens first), so this slightly overestimates the
        actual redemption -- amount*Min ends up set a little high. The
        default slippage buffer absorbs it in practice; not fixed here since
        computing the exact fee-mint amount ahead of the real burn call
        would require duplicating the pair's own accounting.
        """
        reserve0, reserve1, _ = pair.functions.getReserves().call()
        total_supply = pair.functions.totalSupply().call()
        token0 = pair.functions.token0().call()

        raw0 = (liquidity_base * reserve0) // total_supply
        raw1 = (liquidity_base * reserve1) // total_supply

        if token0.lower() == Web3.to_checksum_address(token_a).lower():
            return raw0, raw1
        return raw1, raw0

    def _direct_pair_has_liquidity(self, token_a: str, token_b: str) -> bool:
        """
        Whether a direct Uniswap V2 pair exists for token_a/token_b and has
        non-zero reserves on both sides. Used by _build_path to prefer a
        direct route over a wrapped-native hop when a liquid direct pool
        exists -- routing USDC/DAI through WETH would otherwise pay the
        0.3% fee twice and take two price impacts instead of one. Never
        raises: a missing or dry pair just means "no", so _build_path can
        fall back to the wrapped-native route.
        """
        try:
            pair = self._pair(token_a, token_b)
        except ToolException:
            return False
        reserve0, reserve1, _ = pair.functions.getReserves().call()
        return reserve0 > 0 and reserve1 > 0

    def _build_path(self, token_in: str, token_out: str) -> list[str]:
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        native_wrapped = self.native_wrapped_address
        if (
            native_wrapped is not None
            and token_in != native_wrapped
            and token_out != native_wrapped
            and not self._direct_pair_has_liquidity(token_in, token_out)
        ):
            return [token_in, native_wrapped, token_out]
        return [token_in, token_out]

    def _call(
        self,
        contract: Contract,
        fn_name: str,
        args: list,
        *,
        value: int = 0,
        role: str,
        description: str,
    ) -> dict:
        """
        Builds one account-agnostic call: (to, value, data) plus metadata.
        Pure ABI encoding -- makes no RPC request, so it works identically
        whether the caller is an EOA or a smart-contract wallet.
        """
        try:
            data = contract.encode_abi(abi_element_identifier=fn_name, args=args)
        except (ValueError, MismatchedABI) as err:
            raise ToolException(f"Could not encode {fn_name} call: {err}") from err
        return {
            "to": Web3.to_checksum_address(contract.address),
            "value": int(value),
            "data": data,
            "role": role,
            "description": description,
        }

    def _plan(
        self,
        calls: list[dict],
        *,
        from_address: str,
        summary: dict,
        nonce: int | None = None,
    ) -> dict:
        """
        Assembles an execution plan from an ordered list of account-agnostic
        calls. calls is always populated; transactions is only rendered in
        "eoa" tx_mode (see _render_eoa) and is None in "calls" mode, where a
        smart-contract wallet's own batch executor consumes calls directly.
        """
        plan = {
            "calls": calls,
            "transactions": None,
            "chain_id": self.w3.eth.chain_id,
            "summary": summary,
        }
        if self.tx_mode == "eoa":
            plan["transactions"] = self._render_eoa(calls, from_address, nonce)
        return plan

    def _fee_params(self) -> dict:
        """
        EIP-1559 fee fields when the chain's latest block reports a base fee,
        otherwise legacy gasPrice. Read once per plan and reused across every
        transaction in it, so a multi-call plan carries one consistent fee
        snapshot instead of a fresh (and possibly inconsistent) one per call.
        """
        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas")
        if base_fee is None:
            return {"gasPrice": self.w3.eth.gas_price}
        max_priority_fee = self.w3.eth.max_priority_fee
        return {
            "maxFeePerGas": base_fee * 2 + max_priority_fee,
            "maxPriorityFeePerGas": max_priority_fee,
        }

    def _default_gas(self, call: dict) -> int:
        """Static fallback gas limit for a call whose gas could not be
        estimated yet (see _gas_for), keyed by the call's role."""
        return self.default_gas.get(call["role"], 300_000)

    def _gas_for(
        self, call: dict, sender: str, *, has_pending_prerequisite: bool
    ) -> tuple[int, bool]:
        """
        Returns (gas_limit, was_estimated).

        A call whose prerequisite approval is earlier in this same plan
        cannot be simulated yet -- the allowance is not on-chain until that
        earlier call is mined. For those, fall back to a static limit
        instead of failing the whole build. The first call in a plan has no
        such excuse, so its revert is still fatal and surfaces to the
        caller.
        """
        if not self.estimate_gas:
            return self._default_gas(call), False
        try:
            estimate = self.w3.eth.estimate_gas(
                {
                    "from": sender,
                    "to": call["to"],
                    "value": call["value"],
                    "data": call["data"],
                }
            )
            return int(estimate * self.gas_buffer), True
        except (ContractLogicError, ValueError) as err:
            if has_pending_prerequisite:
                return self._default_gas(call), False
            raise ToolException(f"Transaction would revert: {err}") from err

    def _render_eoa(
        self, calls: list[dict], from_address: str, nonce: int | None = None
    ) -> list[dict]:
        """Renders calls as unsigned, signable EOA transactions with
        sequential nonces and one shared fee snapshot."""
        sender = Web3.to_checksum_address(from_address)
        base_nonce = (
            nonce
            if nonce is not None
            else self.w3.eth.get_transaction_count(sender, "pending")
        )
        fees = self._fee_params()
        chain_id = self.w3.eth.chain_id

        txs = []
        for index, call in enumerate(calls):
            gas, estimated = self._gas_for(call, sender, has_pending_prerequisite=index > 0)
            txs.append(
                {
                    "from": sender,
                    "to": call["to"],
                    "value": call["value"],
                    "data": call["data"],
                    "nonce": base_nonce + index,
                    "chainId": chain_id,
                    "gas": gas,
                    "gas_estimated": estimated,
                    **fees,
                }
            )
        return txs

    def _approval_calls(
        self, spender: str, approvals: list[tuple[Contract, int, str]]
    ) -> tuple[list[dict], list[dict]]:
        """
        Builds the approve() call(s) a set of token pulls needs. Returns
        (leading, trailing): leading always has one approve call per
        approval, in order; trailing has a matching approve(spender, 0) for
        each approval, but only when reset_residual_approvals is enabled --
        it is the caller's job to decide whether to append trailing at all
        (skip it entirely for a call that always pulls its exact approved
        amount, since a reset after that is a guaranteed no-op).
        """
        spender = Web3.to_checksum_address(spender)
        leading, trailing = [], []
        for token, amount_base, label in approvals:
            leading.append(
                self._call(
                    token,
                    "approve",
                    [spender, amount_base],
                    role="approve",
                    description=f"Approve {spender} to spend {label}",
                )
            )
            if self.reset_residual_approvals:
                trailing.append(
                    self._call(
                        token,
                        "approve",
                        [spender, 0],
                        role="approve_reset",
                        description=f"Clear residual {label} allowance for {spender}",
                    )
                )
        return leading, trailing

    @staticmethod
    def _deadline(deadline_secs: int) -> int:
        return int(time.time()) + deadline_secs

    def _require_native_wrapped(self) -> str:
        if not self.native_wrapped_address:
            raise ToolException(
                "This toolkit was not configured with a native_wrapped_address "
                "(e.g. WETH), so native-asset swaps can't be built. Pass "
                "native_wrapped_address to the constructor, or use "
                "UniswapV2Toolkit.for_chain(...) for a chain that has one "
                "registered."
            )
        return self.native_wrapped_address

    def _quote_amounts_out(
        self, amount_in_base: int, path: list[str], *, label_in: str, label_out: str
    ) -> list[int]:
        try:
            return self.router.functions.getAmountsOut(amount_in_base, path).call()
        except ContractLogicError as err:
            raise ToolException(
                f"No Uniswap V2 liquidity path found for {label_in} -> "
                f"{label_out}. The pool may not exist or have insufficient "
                f"reserves."
            ) from err

    def _quote_amounts_in(
        self, amount_out_base: int, path: list[str], *, label_in: str, label_out: str
    ) -> list[int]:
        try:
            return self.router.functions.getAmountsIn(amount_out_base, path).call()
        except ContractLogicError as err:
            raise ToolException(
                f"No Uniswap V2 liquidity path found for {label_in} -> "
                f"{label_out}. The pool may not exist or have insufficient "
                f"reserves."
            ) from err

    # ---- balance/allowance-independent sufficiency checks ----
    #
    # Shared by the is_*_sufficient tools (which return a bool/dict for an
    # agent to inspect) and the write tools' preflight step (which raises
    # instead, when preflight=True). Neither reads an allowance -- they only
    # answer "does this address hold enough", the same question gas
    # estimation used to answer by accident before write tools could build a
    # plan ahead of a standing approval.

    def _token_balance(self, token_address: str, owner_address: str) -> int:
        return (
            self._erc20(token_address)
            .functions.balanceOf(Web3.to_checksum_address(owner_address))
            .call()
        )

    def _native_balance(self, owner_address: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(owner_address))

    def _lp_balance(self, pair: Contract, owner_address: str) -> int:
        return pair.functions.balanceOf(Web3.to_checksum_address(owner_address)).call()

    def _has_token_balance(
        self, token_address: str, amount_base: int, owner_address: str
    ) -> bool:
        return self._token_balance(token_address, owner_address) >= amount_base

    def _has_native_balance(self, amount_base: int, owner_address: str) -> bool:
        return self._native_balance(owner_address) >= amount_base

    def _has_lp_balance(self, pair: Contract, amount_base: int, owner_address: str) -> bool:
        return self._lp_balance(pair, owner_address) >= amount_base

    def _derived_token_input_required(
        self, token_in: str, token_out: str, amount_out_base: int, slippage_bps: int
    ) -> int:
        """Required token_in, in base units, to receive amount_out_base of
        token_out via a *ForExactTokens swap -- a live quote (getAmountsIn)
        plus a slippage buffer. Shared by is_derived_token_input_sufficient
        and swap_tokens_for_exact_tokens/swap_tokens_for_exact_eth, so the
        quote+buffer math is computed in exactly one place."""
        path = self._build_path(token_in, token_out)
        amounts = self._quote_amounts_in(
            amount_out_base, path, label_in=token_in, label_out=token_out
        )
        return amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

    def _derived_native_input_required(
        self, token_out: str, amount_out_base: int, slippage_bps: int
    ) -> int:
        """Native-asset equivalent of _derived_token_input_required, for
        swap_eth_for_exact_tokens and is_derived_native_input_sufficient."""
        native_wrapped = self._require_native_wrapped()
        path = self._build_path(native_wrapped, token_out)
        amounts = self._quote_amounts_in(
            amount_out_base, path, label_in="the native asset", label_out=token_out
        )
        return amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

    def _require_token_balance(
        self,
        token_address: str,
        amount_base: int,
        owner_address: str,
        *,
        decimals: int,
        purpose: str,
    ) -> None:
        """Preflight check for write tools: raises ToolException naming the
        held amount, the required amount, and the shortfall, when
        owner_address doesn't hold enough token_address for purpose."""
        balance = self._token_balance(token_address, owner_address)
        if balance < amount_base:
            raise ToolException(
                f"{owner_address} needs {amount_base / 10**decimals} of "
                f"{token_address} for {purpose} but only holds "
                f"{balance / 10**decimals} -- short by "
                f"{(amount_base - balance) / 10**decimals}."
            )

    def _require_native_balance(
        self, amount_base: int, owner_address: str, *, purpose: str
    ) -> None:
        """Native-asset equivalent of _require_token_balance."""
        balance = self._native_balance(owner_address)
        if balance < amount_base:
            raise ToolException(
                f"{owner_address} needs {amount_base / 10**18} of the native "
                f"asset for {purpose} but only holds {balance / 10**18} -- "
                f"short by {(amount_base - balance) / 10**18}."
            )

    def _require_lp_balance(
        self,
        pair: Contract,
        amount_base: int,
        owner_address: str,
        *,
        decimals: int,
        purpose: str,
    ) -> None:
        """LP-token equivalent of _require_token_balance. decimals is the
        pair's own decimals() -- Uniswap V2 pairs hardcode 18, but this stays
        consistent with the rest of the toolkit reading it live rather than
        assuming, in case a fork's pair contract differs."""
        balance = self._lp_balance(pair, owner_address)
        if balance < amount_base:
            raise ToolException(
                f"{owner_address} needs {amount_base / 10**decimals} LP "
                f"tokens for {purpose} but only holds "
                f"{balance / 10**decimals} -- short by "
                f"{(amount_base - balance) / 10**decimals}."
            )

    # ---- LangChain tools ----

    def get_tools(self) -> list:
        """
        Returns LangChain tools bound to this toolkit's RPC/router/factory
        configuration. Pass these directly into an agent's tools=[...] list.
        """
        toolkit = self

        @tool
        def get_quote_in(token_in: str, token_out: str, amount_out: float) -> dict:
            """
            Returns how much of token_in is required to receive an exact amount
            of token_out, via the Uniswap V2 router's getAmountsIn. Routes through
            this toolkit's configured native-wrapped token when neither token is
            that token and one was configured.

            Use this tool when the user wants to know the cost of acquiring a
            specific amount of a token (e.g. "how much USDC do I need to buy
            exactly 100 DAI?").

            Args:
                token_in: Contract address of the token being spent.
                token_out: Contract address of the token being received.
                amount_out: The exact amount of token_out to receive, in whole
                    units (e.g. 100 for 100 tokens, adjusted for that token's
                    decimals internally).

            Returns:
                A dict with:
                  - amount_in (float): required token_in in whole units.
                  - amount_out (float): the requested token_out amount, echoed back.
                  - path (list[str]): the token address path used for the quote.
            """
            decimals_in = toolkit._decimals(token_in)
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in=token_in, label_out=token_out
            )

            return {
                "amount_in": amounts[0] / 10**decimals_in,
                "amount_out": amount_out,
                "path": path,
            }

        @tool
        def get_quote_out(token_in: str, token_out: str, amount_in: float) -> dict:
            """
            Returns how much of token_out will be received when spending an exact
            amount of token_in, via the Uniswap V2 router's getAmountsOut. Routes
            through this toolkit's configured native-wrapped token when neither
            token is that token and one was configured.

            Use this tool when the user wants to know how much they'll receive
            for a given spend (e.g. "how much DAI will I get for 100 USDC?").

            Args:
                token_in: Contract address of the token being spent.
                token_out: Contract address of the token being received.
                amount_in: The exact amount of token_in to spend, in whole units
                    (e.g. 100 for 100 tokens, adjusted for that token's decimals
                    internally).

            Returns:
                A dict with:
                  - amount_in (float): the token_in amount, echoed back.
                  - amount_out (float): expected token_out in whole units.
                  - path (list[str]): the token address path used for the quote.
            """
            decimals_in = toolkit._decimals(token_in)
            decimals_out = toolkit._decimals(token_out)
            amount_in_base = toolkit._to_base_units(amount_in, decimals_in)
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in=token_in, label_out=token_out
            )

            return {
                "amount_in": amount_in,
                "amount_out": amounts[-1] / 10**decimals_out,
                "path": path,
            }

        @tool
        def get_pool_quote(token_a: str, token_b: str, amount_a: float) -> dict:
            """
            Returns the proportional token_b amount required to match a given
            token_a deposit in a Uniswap V2 pool, using live pool reserves and
            the router's quote().

            Use this tool when the user wants to preview how much of the second
            token they need to provide before adding liquidity (e.g. "how much
            WETH do I need to pair with 2500 DAI?").

            Args:
                token_a: Contract address of the first token.
                token_b: Contract address of the second token.
                amount_a: The amount of token_a to deposit, in whole units
                    (e.g. 2500 for 2500 DAI).

            Returns:
                A dict with:
                  - amount_a (float): token_a deposit, echoed back.
                  - amount_b_desired (float): required token_b in whole units.
            """
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)
            amount_a_base = toolkit._to_base_units(amount_a, decimals_a)
            amount_b_desired_base = toolkit._quote_deposit_base(
                token_a, token_b, amount_a_base
            )

            return {
                "amount_a": amount_a,
                "amount_b_desired": amount_b_desired_base / 10**decimals_b,
            }

        @tool
        def get_lp_amounts(token_a: str, token_b: str, lp_amount: float) -> dict:
            """
            Returns the expected token amounts redeemable by burning a given
            amount of Uniswap V2 LP tokens, derived from live reserves using the
            proportional share formula (liquidity * reserve / totalSupply).

            Use this tool when the user wants to preview returns before removing
            liquidity (e.g. "how much DAI and WETH will I get for 0.5 LP
            tokens?").

            Args:
                token_a: Contract address of the first token in the pair.
                token_b: Contract address of the second token in the pair.
                lp_amount: The amount of LP tokens to burn, in whole units
                    (e.g. 0.5).

            Returns:
                A dict with:
                  - expected_a (float): expected token_a return in whole units.
                  - expected_b (float): expected token_b return in whole units.
            """
            pair = toolkit._pair(token_a, token_b)
            lp_decimals = pair.functions.decimals().call()
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)
            liquidity = toolkit._to_base_units(lp_amount, lp_decimals)

            expected_a_base, expected_b_base = toolkit._lp_redemption_base(
                pair, token_a, liquidity
            )

            return {
                "expected_a": expected_a_base / 10**decimals_a,
                "expected_b": expected_b_base / 10**decimals_b,
            }

        @tool
        def get_liquidity_token_balance(
            owner_address: str, token_a: str, token_b: str
        ) -> float:
            """
            Retrieves an address's balance of Uniswap V2 liquidity tokens for a
            given pair.

            Use this tool when the user wants to check how much liquidity a
            given address has provided to a Uniswap V2 pool.

            Args:
                owner_address: The address whose LP token balance to check.
                token_a: Contract address of the first token in the pair.
                token_b: Contract address of the second token in the pair.

            Returns:
                The owner's balance of liquidity tokens for the pair, in whole
                units (e.g. 10.5).
            """
            pair = toolkit._pair(token_a, token_b)
            decimals = pair.functions.decimals().call()
            balance = pair.functions.balanceOf(Web3.to_checksum_address(owner_address)).call()
            return balance / 10**decimals

        @tool
        def is_token_balance_sufficient(
            token_address: str, amount: float, owner_address: str
        ) -> bool:
            """
            Checks whether owner_address holds at least `amount` of
            token_address. Use this before a swap, approval, or liquidity
            deposit that pulls tokens from a wallet, to confirm the balance
            covers it before spending gas building/submitting a
            transaction. Read-only -- checks the raw ERC20 balance only, not
            any allowance.

            Args:
                token_address: Contract address of the token to check.
                amount: The amount required, in whole units.
                owner_address: The address whose balance to check.

            Returns:
                True if owner_address's balance of token_address is >=
                amount.
            """
            decimals = toolkit._decimals(token_address)
            amount_base = toolkit._to_base_units(amount, decimals)
            return toolkit._has_token_balance(token_address, amount_base, owner_address)

        @tool
        def is_native_balance_sufficient(amount: float, owner_address: str) -> bool:
            """
            Checks whether owner_address holds at least `amount` of the
            chain's native asset (ETH, BNB, etc.). Use this before a swap or
            liquidity deposit that sends native-asset value, to confirm the
            balance covers it -- this only checks the value being sent, not
            gas paid on top of it. "Native asset" here is a generic internal
            label -- this works identically on every supported network.

            Args:
                amount: The amount required, in whole units (e.g. 1.5).
                owner_address: The address whose balance to check.

            Returns:
                True if owner_address's native-asset balance is >= amount.
            """
            amount_base = toolkit._to_base_units(amount, 18)
            return toolkit._has_native_balance(amount_base, owner_address)

        @tool
        def is_derived_token_input_sufficient(
            token_in: str,
            token_out: str,
            amount_out: float,
            owner_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        ) -> dict:
            """
            Checks whether owner_address holds enough token_in to cover a
            swap_tokens_for_exact_tokens call (or swap_tokens_for_exact_eth,
            passing this toolkit's native_wrapped_address as token_out) for
            amount_out, including a slippage buffer. The required input is
            derived from a live quote (getAmountsIn), the same one those
            swap tools use internally.

            Use this before calling swap_tokens_for_exact_tokens or
            swap_tokens_for_exact_eth, to confirm the balance covers the
            swap before spending gas building/submitting it.

            Args:
                token_in: Contract address of the token being spent.
                token_out: Contract address of the token being received.
                amount_out: The exact amount of token_out the swap should
                    produce, in whole units.
                owner_address: The address whose token_in balance to check.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%) -- pass the same value you intend to use
                    for the swap tool call, since a mismatch would derive a
                    different required input.

            Returns:
                A dict with:
                  - is_sufficient (bool): True if the balance covers the
                    derived input requirement.
                  - required_input (float): The token_in amount required,
                    including the slippage buffer, in whole units.
            """
            decimals_in = toolkit._decimals(token_in)
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            required_base = toolkit._derived_token_input_required(
                token_in, token_out, amount_out_base, slippage_bps
            )

            return {
                "is_sufficient": toolkit._has_token_balance(
                    token_in, required_base, owner_address
                ),
                "required_input": required_base / 10**decimals_in,
            }

        @tool
        def is_derived_native_input_sufficient(
            token_out: str,
            amount_out: float,
            owner_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        ) -> dict:
            """
            Checks whether owner_address holds enough of the chain's native
            asset (ETH, BNB, etc.) to cover a swap_eth_for_exact_tokens call
            for amount_out, including a slippage buffer. The required input
            is derived from a live quote (getAmountsIn), the same one that
            swap tool uses internally. Requires this toolkit to have been
            configured with native_wrapped_address. "Native asset" here is a
            generic internal label -- this works identically on every
            supported network.

            Use this before calling swap_eth_for_exact_tokens, to confirm
            the balance covers the swap before spending gas
            building/submitting it -- this only checks the swap's value, not
            gas paid on top of it.

            Args:
                token_out: Contract address of the token being received.
                amount_out: The exact amount of token_out the swap should
                    produce, in whole units.
                owner_address: The address whose native-asset balance to
                    check.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%) -- pass the same value you intend to use
                    for the swap tool call, since a mismatch would derive a
                    different required input.

            Returns:
                A dict with:
                  - is_sufficient (bool): True if the balance covers the
                    derived input requirement.
                  - required_input (float): The native-asset amount
                    required, including the slippage buffer, in whole units.
            """
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            required_base = toolkit._derived_native_input_required(
                token_out, amount_out_base, slippage_bps
            )

            return {
                "is_sufficient": toolkit._has_native_balance(required_base, owner_address),
                "required_input": required_base / 10**18,
            }

        @tool
        def is_liquidity_sufficient(
            token_a: str, amount_a: float, token_b: str, owner_address: str
        ) -> dict:
            """
            Checks whether owner_address holds enough of both tokens to
            cover an add_liquidity deposit of amount_a of token_a. The
            required token_b amount is derived from live pool reserves (the
            same quote add_liquidity uses internally) -- no need to
            pre-compute it.

            Use this before calling add_liquidity, to confirm both balances
            cover the deposit before spending gas building/submitting it.

            Args:
                token_a: Contract address of the first token to deposit.
                amount_a: The desired token_a deposit amount, in whole
                    units.
                token_b: Contract address of the second token to deposit.
                owner_address: The address whose balances to check.

            Returns:
                A dict with:
                  - is_sufficient (bool): True if the balance of both tokens
                    covers the deposit.
                  - required_b (float): The proportional token_b amount
                    required, in whole units.
            """
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)
            amount_a_base = toolkit._to_base_units(amount_a, decimals_a)
            amount_b_required_base = toolkit._quote_deposit_base(
                token_a, token_b, amount_a_base
            )

            is_sufficient = toolkit._has_token_balance(
                token_a, amount_a_base, owner_address
            ) and toolkit._has_token_balance(token_b, amount_b_required_base, owner_address)
            return {
                "is_sufficient": is_sufficient,
                "required_b": amount_b_required_base / 10**decimals_b,
            }

        @tool
        def is_liquidity_sufficient_eth(
            token: str, amount_token: float, owner_address: str
        ) -> dict:
            """
            Checks whether owner_address holds enough of token and the
            chain's native asset (ETH, BNB, etc.) to cover an
            add_liquidity_eth deposit of amount_token of token. The required
            native-asset amount is derived from live pool reserves (the same
            quote add_liquidity_eth uses internally). Requires this toolkit
            to have been configured with native_wrapped_address. "Native
            asset" here is a generic internal label -- this works
            identically on every supported network.

            Use this before calling add_liquidity_eth, to confirm both
            balances cover the deposit before spending gas
            building/submitting it -- the native-asset check only covers the
            deposit value, not gas paid on top of it.

            Args:
                token: Contract address of the ERC20 token to deposit
                    alongside the native asset.
                amount_token: The desired token deposit amount, in whole
                    units.
                owner_address: The address whose balances to check.

            Returns:
                A dict with:
                  - is_sufficient (bool): True if both balances cover the
                    deposit.
                  - required_native (float): The native-asset amount
                    required, in whole units.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_token = toolkit._decimals(token)
            amount_token_base = toolkit._to_base_units(amount_token, decimals_token)
            amount_native_required_base = toolkit._quote_deposit_base(
                token, native_wrapped, amount_token_base
            )

            is_sufficient = toolkit._has_token_balance(
                token, amount_token_base, owner_address
            ) and toolkit._has_native_balance(amount_native_required_base, owner_address)
            return {
                "is_sufficient": is_sufficient,
                "required_native": amount_native_required_base / 10**18,
            }

        @tool
        def is_liquidity_removal_sufficient(
            token_a: str, token_b: str, lp_amount: float, owner_address: str
        ) -> bool:
            """
            Checks whether owner_address holds at least lp_amount of the
            pair's LP token. Use this before calling remove_liquidity or
            remove_liquidity_eth (pass this toolkit's
            native_wrapped_address as token_b for the latter, matching what
            that tool pairs against internally), to confirm the balance
            covers the burn before spending gas building/submitting it.

            Args:
                token_a: Contract address of the first token in the pair.
                token_b: Contract address of the second token in the pair.
                lp_amount: The amount of LP tokens to burn, in whole units.
                owner_address: The address whose LP token balance to check.

            Returns:
                True if owner_address holds at least lp_amount of the
                pair's LP token.
            """
            pair = toolkit._pair(token_a, token_b)
            decimals = pair.functions.decimals().call()
            lp_amount_base = toolkit._to_base_units(lp_amount, decimals)
            return toolkit._has_lp_balance(pair, lp_amount_base, owner_address)

        @tool
        def approve_token(
            token_address: str,
            spender_address: str,
            from_address: str,
            amount: float = 0,
            unlimited: bool = False,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an execution plan containing a single ERC20 approve
            call, authorizing spender_address to transfer up to `amount` of
            token_address (or an unlimited amount, if unlimited=True) on
            behalf of from_address. The swap and liquidity tools below
            already include their own approval call(s) automatically,
            sized to what each pulls -- use this tool for explicit/manual
            control instead, e.g. granting an allowance outside of any swap
            or deposit flow, or to a spender other than this toolkit's
            router.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- for approve_token,
            just the one approve call. Execute it; if your account supports
            batching it can be included in a larger atomic batch alongside
            other calls. In EOA mode `transactions` holds the same call
            rendered as an unsigned, signable transaction; in calls mode it
            is None. `summary` holds the amounts in whole units and is safe
            to show the user. This tool never signs or broadcasts anything.

            Args:
                token_address: Contract address of the token to approve.
                spender_address: Address being granted the allowance --
                    usually this toolkit's router address.
                from_address: The address that will sign this transaction --
                    i.e. the current token holder granting the approval.
                amount: The amount to approve, in whole units (e.g. 100 for
                    100 tokens, adjusted for that token's decimals
                    internally). Ignored when unlimited=True.
                unlimited: If True, approves the maximum possible uint256
                    value (2**256 - 1) instead of amount -- the standard
                    effectively-unlimited approval. Prefer this over
                    passing a very large amount: token contracts vary in
                    how many bits they allow for an allowance, and some
                    reject values larger than what fits in a uint256 once
                    scaled by decimals, which this tool cannot predict
                    ahead of a live transaction.
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used.
            """
            spender = Web3.to_checksum_address(spender_address)
            if unlimited:
                amount_base = 2**256 - 1
                label = "an unlimited amount"
            else:
                decimals = toolkit._decimals(token_address)
                amount_base = toolkit._to_base_units(amount, decimals)
                label = f"{amount} of {token_address}"
            erc20 = toolkit._erc20(token_address)
            call = toolkit._call(
                erc20,
                "approve",
                [spender, amount_base],
                role="approve",
                description=f"Approve {spender} to spend {label}",
            )
            return toolkit._plan(
                [call],
                from_address=from_address,
                summary={
                    "token": token_address,
                    "spender": spender,
                    "amount": None if unlimited else amount,
                    "unlimited": unlimited,
                },
                nonce=nonce,
            )

        @tool
        def swap_exact_tokens_for_tokens(
            token_in: str,
            token_out: str,
            amount_in: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps an exact amount of token_in for
            token_out via the router's swapExactTokensForTokens.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- any required
            approval first, then the action, then an approval reset where
            the router may pull less than it was approved for. Execute all
            of them, in order; if your account supports batching, execute
            them atomically in one transaction. In EOA mode `transactions`
            holds the same calls rendered as unsigned, signable
            transactions with sequential nonces already assigned; in calls
            mode it is None. `summary` holds the amounts in whole units and
            is safe to show the user. This tool never signs or broadcasts
            anything.

            Args:
                token_in: Contract address of the token being sold.
                token_out: Contract address of the token being bought.
                amount_in: The exact amount of token_in to sell, in whole
                    units.
                from_address: The address that will sign this transaction --
                    also the recipient of token_out unless recipient is set.
                recipient: Optional address to receive token_out. Defaults to
                    from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used. The
                    approval call ahead of the swap, if any, gets this
                    nonce; the swap gets the next one.
            """
            decimals_in = toolkit._decimals(token_in)
            decimals_out = toolkit._decimals(token_out)
            amount_in_base = toolkit._to_base_units(amount_in, decimals_in)
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token_in,
                    amount_in_base,
                    from_address,
                    decimals=decimals_in,
                    purpose="this swap",
                )
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in=token_in, label_out=token_out
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            to = Web3.to_checksum_address(recipient or from_address)

            leading, _trailing = toolkit._approval_calls(
                toolkit.router.address,
                [(toolkit._erc20(token_in), amount_in_base, f"{amount_in} of {token_in}")],
            )
            action = toolkit._call(
                toolkit.router,
                "swapExactTokensForTokens",
                [amount_in_base, amount_out_min, path, to, toolkit._deadline(deadline_secs)],
                role="swap",
                description=(
                    f"Swap {amount_in} of {token_in} for at least "
                    f"{amount_out_min / 10**decimals_out} of {token_out}"
                ),
            )

            return toolkit._plan(
                [*leading, action],
                from_address=from_address,
                summary={
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_in": amount_in,
                    "amount_out_min": amount_out_min / 10**decimals_out,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def swap_tokens_for_exact_tokens(
            token_in: str,
            token_out: str,
            amount_out: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps as much of token_in as needed for an
            exact amount of token_out via the router's
            swapTokensForExactTokens. The actual amount pulled is derived
            from a live quote plus slippage_bps and may be less than the
            approved amountInMax -- in EOA mode the plan's last call resets
            any resulting residual approval to zero when
            reset_residual_approvals is enabled (see the constructor).

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- any required
            approval first, then the action, then an approval reset where
            the router may pull less than it was approved for. Execute all
            of them, in order; if your account supports batching, execute
            them atomically in one transaction. In EOA mode `transactions`
            holds the same calls rendered as unsigned, signable
            transactions with sequential nonces already assigned; in calls
            mode it is None. `summary` holds the amounts in whole units and
            is safe to show the user. This tool never signs or broadcasts
            anything.

            Args:
                token_in: Contract address of the token being sold.
                token_out: Contract address of the token being bought.
                amount_out: The exact amount of token_out to receive, in
                    whole units.
                from_address: The address that will sign this transaction --
                    also the recipient of token_out unless recipient is set.
                recipient: Optional address to receive token_out. Defaults to
                    from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax as the quoted input increased by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used; each call
                    in the plan gets the next sequential nonce.
            """
            decimals_in = toolkit._decimals(token_in)
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            amount_in_max = toolkit._derived_token_input_required(
                token_in, token_out, amount_out_base, slippage_bps
            )
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token_in,
                    amount_in_max,
                    from_address,
                    decimals=decimals_in,
                    purpose="this swap",
                )
            path = toolkit._build_path(token_in, token_out)
            to = Web3.to_checksum_address(recipient or from_address)

            leading, trailing = toolkit._approval_calls(
                toolkit.router.address,
                [
                    (
                        toolkit._erc20(token_in),
                        amount_in_max,
                        f"up to {amount_in_max / 10**decimals_in} of {token_in}",
                    )
                ],
            )
            action = toolkit._call(
                toolkit.router,
                "swapTokensForExactTokens",
                [amount_out_base, amount_in_max, path, to, toolkit._deadline(deadline_secs)],
                role="swap",
                description=(
                    f"Swap up to {amount_in_max / 10**decimals_in} of {token_in} for "
                    f"exactly {amount_out} of {token_out}"
                ),
            )

            return toolkit._plan(
                [*leading, action, *trailing],
                from_address=from_address,
                summary={
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_out": amount_out,
                    "amount_in_max": amount_in_max / 10**decimals_in,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def swap_exact_eth_for_tokens(
            token_out: str,
            amount_in: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps an exact amount of the chain's native
            asset (ETH, BNB, etc.) for token_out via the router's
            swapExactETHForTokens. "ETH" in the tool name is a generic
            internal label -- this works identically on every supported
            network. Requires this toolkit to have been configured with
            native_wrapped_address.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- here, just the one
            swap call, with the native-asset amount set as its value (no
            approval is needed to send native value). Execute it; if your
            account supports batching it can be included in a larger atomic
            batch alongside other calls. In EOA mode `transactions` holds
            the same call rendered as an unsigned, signable transaction; in
            calls mode it is None. `summary` holds the amounts in whole
            units and is safe to show the user. This tool never signs or
            broadcasts anything.

            Args:
                token_out: Contract address of the token being bought.
                amount_in: The exact amount of the native asset to spend, in
                    whole units (e.g. 1.5).
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of
                    token_out unless recipient is set.
                recipient: Optional address to receive token_out. Defaults to
                    from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_out = toolkit._decimals(token_out)
            amount_in_base = toolkit._to_base_units(amount_in, 18)
            if toolkit.preflight:
                toolkit._require_native_balance(
                    amount_in_base, from_address, purpose="this swap"
                )
            path = toolkit._build_path(native_wrapped, token_out)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in="the native asset", label_out=token_out
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            to = Web3.to_checksum_address(recipient or from_address)

            action = toolkit._call(
                toolkit.router,
                "swapExactETHForTokens",
                [amount_out_min, path, to, toolkit._deadline(deadline_secs)],
                value=amount_in_base,
                role="swap",
                description=(
                    f"Swap {amount_in} of the native asset for at least "
                    f"{amount_out_min / 10**decimals_out} of {token_out}"
                ),
            )

            return toolkit._plan(
                [action],
                from_address=from_address,
                summary={
                    "token_out": token_out,
                    "amount_in": amount_in,
                    "amount_out_min": amount_out_min / 10**decimals_out,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def swap_eth_for_exact_tokens(
            token_out: str,
            amount_out: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps however much of the chain's native
            asset (ETH, BNB, etc.) is needed for an exact amount of
            token_out via the router's swapETHForExactTokens. The router
            refunds any unused native asset to from_address within the same
            on-chain transaction. "ETH" in the tool name is a generic
            internal label -- this works identically on every supported
            network. Requires this toolkit to have been configured with
            native_wrapped_address.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- here, just the one
            swap call, with the derived amountInMax set as its value (no
            approval is needed to send native value; unused value is
            refunded on-chain by the router). Execute it; if your account
            supports batching it can be included in a larger atomic batch
            alongside other calls. In EOA mode `transactions` holds the
            same call rendered as an unsigned, signable transaction; in
            calls mode it is None. `summary` holds the amounts in whole
            units and is safe to show the user. This tool never signs or
            broadcasts anything.

            Args:
                token_out: Contract address of the token being bought.
                amount_out: The exact amount of token_out to receive, in
                    whole units.
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of
                    token_out unless recipient is set.
                recipient: Optional address to receive token_out. Defaults to
                    from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax (the tx value) as the quoted input increased
                    by this percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            amount_in_max = toolkit._derived_native_input_required(
                token_out, amount_out_base, slippage_bps
            )
            if toolkit.preflight:
                toolkit._require_native_balance(
                    amount_in_max, from_address, purpose="this swap"
                )
            path = toolkit._build_path(native_wrapped, token_out)
            to = Web3.to_checksum_address(recipient or from_address)

            action = toolkit._call(
                toolkit.router,
                "swapETHForExactTokens",
                [amount_out_base, path, to, toolkit._deadline(deadline_secs)],
                value=amount_in_max,
                role="swap",
                description=(
                    f"Swap up to {amount_in_max / 10**18} of the native asset for "
                    f"exactly {amount_out} of {token_out}"
                ),
            )

            return toolkit._plan(
                [action],
                from_address=from_address,
                summary={
                    "token_out": token_out,
                    "amount_out": amount_out,
                    "amount_in_max": amount_in_max / 10**18,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def swap_exact_tokens_for_eth(
            token_in: str,
            amount_in: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps an exact amount of token_in for the
            chain's native asset (ETH, BNB, etc.) via the router's
            swapExactTokensForETH. "ETH" in the tool name is a generic
            internal label -- this works identically on every supported
            network. Requires this toolkit to have been configured with
            native_wrapped_address.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- any required
            approval first, then the action, then an approval reset where
            the router may pull less than it was approved for. Execute all
            of them, in order; if your account supports batching, execute
            them atomically in one transaction. In EOA mode `transactions`
            holds the same calls rendered as unsigned, signable
            transactions with sequential nonces already assigned; in calls
            mode it is None. `summary` holds the amounts in whole units and
            is safe to show the user. This tool never signs or broadcasts
            anything.

            Args:
                token_in: Contract address of the token being sold.
                amount_in: The exact amount of token_in to sell, in whole
                    units.
                from_address: The address that will sign this transaction --
                    also the recipient of the native asset unless recipient
                    is set.
                recipient: Optional address to receive the native asset.
                    Defaults to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used. The
                    approval call ahead of the swap, if any, gets this
                    nonce; the swap gets the next one.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_in = toolkit._decimals(token_in)
            amount_in_base = toolkit._to_base_units(amount_in, decimals_in)
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token_in,
                    amount_in_base,
                    from_address,
                    decimals=decimals_in,
                    purpose="this swap",
                )
            path = toolkit._build_path(token_in, native_wrapped)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in=token_in, label_out="the native asset"
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            to = Web3.to_checksum_address(recipient or from_address)

            leading, _trailing = toolkit._approval_calls(
                toolkit.router.address,
                [(toolkit._erc20(token_in), amount_in_base, f"{amount_in} of {token_in}")],
            )
            action = toolkit._call(
                toolkit.router,
                "swapExactTokensForETH",
                [amount_in_base, amount_out_min, path, to, toolkit._deadline(deadline_secs)],
                role="swap",
                description=(
                    f"Swap {amount_in} of {token_in} for at least "
                    f"{amount_out_min / 10**18} of the native asset"
                ),
            )

            return toolkit._plan(
                [*leading, action],
                from_address=from_address,
                summary={
                    "token_in": token_in,
                    "amount_in": amount_in,
                    "amount_out_min": amount_out_min / 10**18,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def swap_tokens_for_exact_eth(
            token_in: str,
            amount_out: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that swaps however much of token_in is needed for
            an exact amount of the chain's native asset (ETH, BNB, etc.) via
            the router's swapTokensForExactETH. "ETH" in the tool/parameter
            names is a generic internal label -- this works identically on
            every supported network. Requires this toolkit to have been
            configured with native_wrapped_address. The actual amount
            pulled is derived from a live quote plus slippage_bps and may
            be less than the approved amountInMax -- in EOA mode the plan's
            last call resets any resulting residual approval to zero when
            reset_residual_approvals is enabled (see the constructor).

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- any required
            approval first, then the action, then an approval reset where
            the router may pull less than it was approved for. Execute all
            of them, in order; if your account supports batching, execute
            them atomically in one transaction. In EOA mode `transactions`
            holds the same calls rendered as unsigned, signable
            transactions with sequential nonces already assigned; in calls
            mode it is None. `summary` holds the amounts in whole units and
            is safe to show the user. This tool never signs or broadcasts
            anything.

            Args:
                token_in: Contract address of the token being sold.
                amount_out: The exact amount of the native asset to receive,
                    in whole units (e.g. 1.5).
                from_address: The address that will sign this transaction --
                    also the recipient of the native asset unless recipient
                    is set.
                recipient: Optional address to receive the native asset.
                    Defaults to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax as the quoted input increased by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used; each call
                    in the plan gets the next sequential nonce.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_in = toolkit._decimals(token_in)
            amount_out_base = toolkit._to_base_units(amount_out, 18)
            amount_in_max = toolkit._derived_token_input_required(
                token_in, native_wrapped, amount_out_base, slippage_bps
            )
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token_in,
                    amount_in_max,
                    from_address,
                    decimals=decimals_in,
                    purpose="this swap",
                )
            path = toolkit._build_path(token_in, native_wrapped)
            to = Web3.to_checksum_address(recipient or from_address)

            leading, trailing = toolkit._approval_calls(
                toolkit.router.address,
                [
                    (
                        toolkit._erc20(token_in),
                        amount_in_max,
                        f"up to {amount_in_max / 10**decimals_in} of {token_in}",
                    )
                ],
            )
            action = toolkit._call(
                toolkit.router,
                "swapTokensForExactETH",
                [amount_out_base, amount_in_max, path, to, toolkit._deadline(deadline_secs)],
                role="swap",
                description=(
                    f"Swap up to {amount_in_max / 10**decimals_in} of {token_in} for "
                    f"exactly {amount_out} of the native asset"
                ),
            )

            return toolkit._plan(
                [*leading, action, *trailing],
                from_address=from_address,
                summary={
                    "token_in": token_in,
                    "amount_out": amount_out,
                    "amount_in_max": amount_in_max / 10**decimals_in,
                    "path": path,
                },
                nonce=nonce,
            )

        @tool
        def add_liquidity(
            token_a: str,
            token_b: str,
            amount_a: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that adds liquidity to a Uniswap V2 token/token
            pool via the router's addLiquidity. The proportional token_b
            amount is derived from live pool reserves via get_pool_quote's
            logic, so the deposit matches the current pool ratio. The pool
            ratio may mean the router pulls less than the approved amount
            of either token -- in EOA mode the plan's last call(s) reset
            any resulting residual approval(s) to zero when
            reset_residual_approvals is enabled (see the constructor).

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- both required
            approvals first, then the deposit, then approval resets where
            the router may pull less than it was approved for. Execute all
            of them, in order; if your account supports batching, execute
            them atomically in one transaction. In EOA mode `transactions`
            holds the same calls rendered as unsigned, signable
            transactions with sequential nonces already assigned; in calls
            mode it is None. `summary` holds the amounts in whole units and
            is safe to show the user. This tool never signs or broadcasts
            anything.

            Args:
                token_a: Contract address of the first token to deposit.
                token_b: Contract address of the second token to deposit.
                amount_a: The desired amount of token_a to deposit, in whole
                    units. The proportional token_b amount is computed from
                    pool reserves automatically.
                from_address: The address that will sign this transaction and
                    that currently holds both tokens -- also the recipient of
                    the LP tokens unless recipient is set.
                recipient: Optional address to receive the LP tokens. Defaults
                    to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both amountAMin and
                    amountBMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the deposit
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used; each call
                    in the plan gets the next sequential nonce.
            """
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)
            amount_a_base = toolkit._to_base_units(amount_a, decimals_a)
            amount_b_desired_base = toolkit._quote_deposit_base(
                token_a, token_b, amount_a_base
            )
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token_a,
                    amount_a_base,
                    from_address,
                    decimals=decimals_a,
                    purpose="this deposit",
                )
                toolkit._require_token_balance(
                    token_b,
                    amount_b_desired_base,
                    from_address,
                    decimals=decimals_b,
                    purpose="this deposit",
                )

            amount_a_min = amount_a_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            amount_b_min = (
                amount_b_desired_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            to = Web3.to_checksum_address(recipient or from_address)

            leading, trailing = toolkit._approval_calls(
                toolkit.router.address,
                [
                    (toolkit._erc20(token_a), amount_a_base, f"{amount_a} of {token_a}"),
                    (
                        toolkit._erc20(token_b),
                        amount_b_desired_base,
                        f"{amount_b_desired_base / 10**decimals_b} of {token_b}",
                    ),
                ],
            )
            action = toolkit._call(
                toolkit.router,
                "addLiquidity",
                [
                    Web3.to_checksum_address(token_a),
                    Web3.to_checksum_address(token_b),
                    amount_a_base,
                    amount_b_desired_base,
                    amount_a_min,
                    amount_b_min,
                    to,
                    toolkit._deadline(deadline_secs),
                ],
                role="add_liquidity",
                description=(
                    f"Add liquidity: {amount_a} of {token_a} and "
                    f"{amount_b_desired_base / 10**decimals_b} of {token_b}"
                ),
            )

            return toolkit._plan(
                [*leading, action, *trailing],
                from_address=from_address,
                summary={
                    "token_a": token_a,
                    "token_b": token_b,
                    "amount_a": amount_a,
                    "amount_b_desired": amount_b_desired_base / 10**decimals_b,
                    "amount_a_min": amount_a_min / 10**decimals_a,
                    "amount_b_min": amount_b_min / 10**decimals_b,
                },
                nonce=nonce,
            )

        @tool
        def add_liquidity_eth(
            token: str,
            amount_token: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that adds liquidity to a Uniswap V2
            token/native-asset pool via the router's addLiquidityETH. The
            proportional native-asset amount is derived from live pool
            reserves so the deposit matches the current pool ratio. "ETH" in
            the tool name is a generic internal label -- this works
            identically on every supported network. Requires this toolkit to
            have been configured with native_wrapped_address. The pool
            ratio may mean the router pulls less than the approved amount
            of token -- in EOA mode the plan's last call resets any
            resulting residual approval to zero when
            reset_residual_approvals is enabled (see the constructor).

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- the required
            approval first, then the deposit (with the derived native-asset
            amount set as its value), then an approval reset where the
            router may pull less than it was approved for. Execute all of
            them, in order; if your account supports batching, execute them
            atomically in one transaction. In EOA mode `transactions` holds
            the same calls rendered as unsigned, signable transactions with
            sequential nonces already assigned; in calls mode it is None.
            `summary` holds the amounts in whole units and is safe to show
            the user. This tool never signs or broadcasts anything.

            Args:
                token: Contract address of the ERC20 token to deposit
                    alongside the native asset.
                amount_token: The desired amount of token to deposit, in
                    whole units. The proportional native-asset amount is
                    computed from pool reserves automatically.
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of the
                    LP tokens unless recipient is set.
                recipient: Optional address to receive the LP tokens. Defaults
                    to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both
                    amountTokenMin and amountETHMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the deposit
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used; each call
                    in the plan gets the next sequential nonce.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_token = toolkit._decimals(token)
            amount_token_base = toolkit._to_base_units(amount_token, decimals_token)
            amount_eth_desired_base = toolkit._quote_deposit_base(
                token, native_wrapped, amount_token_base
            )
            if toolkit.preflight:
                toolkit._require_token_balance(
                    token,
                    amount_token_base,
                    from_address,
                    decimals=decimals_token,
                    purpose="this deposit",
                )
                toolkit._require_native_balance(
                    amount_eth_desired_base, from_address, purpose="this deposit"
                )

            amount_token_min = (
                amount_token_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_eth_min = (
                amount_eth_desired_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            to = Web3.to_checksum_address(recipient or from_address)

            leading, trailing = toolkit._approval_calls(
                toolkit.router.address,
                [(toolkit._erc20(token), amount_token_base, f"{amount_token} of {token}")],
            )
            action = toolkit._call(
                toolkit.router,
                "addLiquidityETH",
                [
                    Web3.to_checksum_address(token),
                    amount_token_base,
                    amount_token_min,
                    amount_eth_min,
                    to,
                    toolkit._deadline(deadline_secs),
                ],
                value=amount_eth_desired_base,
                role="add_liquidity",
                description=(
                    f"Add liquidity: {amount_token} of {token} and "
                    f"{amount_eth_desired_base / 10**18} of the native asset"
                ),
            )

            return toolkit._plan(
                [*leading, action, *trailing],
                from_address=from_address,
                summary={
                    "token": token,
                    "amount_token": amount_token,
                    "amount_eth_desired": amount_eth_desired_base / 10**18,
                    "amount_token_min": amount_token_min / 10**decimals_token,
                    "amount_eth_min": amount_eth_min / 10**18,
                },
                nonce=nonce,
            )

        @tool
        def remove_liquidity(
            token_a: str,
            token_b: str,
            lp_amount: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that removes liquidity from a Uniswap V2 pool via
            the router's removeLiquidity. Expected return amounts for both
            tokens are derived from live pool reserves using the
            proportional share formula (liquidity * reserve / totalSupply).
            The pair's own LP token is approved and pulled -- this always
            pulls exactly lp_amount, so no residual approval is ever left
            behind.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- the required LP
            token approval first, then the withdrawal. Execute both, in
            order; if your account supports batching, execute them
            atomically in one transaction. In EOA mode `transactions` holds
            the same calls rendered as unsigned, signable transactions with
            sequential nonces already assigned; in calls mode it is None.
            `summary` holds the amounts in whole units and is safe to show
            the user. This tool never signs or broadcasts anything.

            Args:
                token_a: Contract address of the first token in the pair.
                token_b: Contract address of the second token in the pair.
                lp_amount: The amount of LP tokens to burn, in whole units
                    (e.g. 0.5).
                from_address: The address that will sign this transaction and
                    that currently holds the LP tokens -- also the recipient
                    of both returned tokens unless recipient is set.
                recipient: Optional address to receive both returned tokens.
                    Defaults to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both amountAMin and
                    amountBMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the withdrawal
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used. The
                    approval call gets this nonce; the withdrawal gets the
                    next one.
            """
            pair = toolkit._pair(token_a, token_b)
            lp_decimals = pair.functions.decimals().call()
            liquidity_base = toolkit._to_base_units(lp_amount, lp_decimals)
            if toolkit.preflight:
                toolkit._require_lp_balance(
                    pair,
                    liquidity_base,
                    from_address,
                    decimals=lp_decimals,
                    purpose="this withdrawal",
                )
            expected_a_base, expected_b_base = toolkit._lp_redemption_base(
                pair, token_a, liquidity_base
            )
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)

            amount_a_min = (
                expected_a_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_b_min = (
                expected_b_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            to = Web3.to_checksum_address(recipient or from_address)

            leading, _trailing = toolkit._approval_calls(
                toolkit.router.address,
                [(pair, liquidity_base, f"{lp_amount} LP tokens for {token_a}/{token_b}")],
            )
            action = toolkit._call(
                toolkit.router,
                "removeLiquidity",
                [
                    Web3.to_checksum_address(token_a),
                    Web3.to_checksum_address(token_b),
                    liquidity_base,
                    amount_a_min,
                    amount_b_min,
                    to,
                    toolkit._deadline(deadline_secs),
                ],
                role="remove_liquidity",
                description=f"Remove {lp_amount} LP tokens for {token_a}/{token_b}",
            )

            return toolkit._plan(
                [*leading, action],
                from_address=from_address,
                summary={
                    "token_a": token_a,
                    "token_b": token_b,
                    "lp_amount": lp_amount,
                    "expected_a": expected_a_base / 10**decimals_a,
                    "expected_b": expected_b_base / 10**decimals_b,
                    "amount_a_min": amount_a_min / 10**decimals_a,
                    "amount_b_min": amount_b_min / 10**decimals_b,
                },
                nonce=nonce,
            )

        @tool
        def remove_liquidity_eth(
            token: str,
            lp_amount: float,
            from_address: str,
            recipient: str | None = None,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds a plan that removes liquidity from a Uniswap V2
            token/native-asset pool via the router's removeLiquidityETH.
            Expected return amounts are derived from live pool reserves
            using the proportional share formula. The router unwraps the
            wrapped-native share to the raw native asset before sending it
            back. "ETH" in the tool/parameter names is a generic internal
            label -- this works identically on every supported network.
            Requires this toolkit to have been configured with
            native_wrapped_address. The pair's own LP token is approved and
            pulled -- this always pulls exactly lp_amount, so no residual
            approval is ever left behind.

            Returns an execution plan: `calls` is the ordered list of
            contract calls this operation consists of -- the required LP
            token approval first, then the withdrawal. Execute both, in
            order; if your account supports batching, execute them
            atomically in one transaction. In EOA mode `transactions` holds
            the same calls rendered as unsigned, signable transactions with
            sequential nonces already assigned; in calls mode it is None.
            `summary` holds the amounts in whole units and is safe to show
            the user. This tool never signs or broadcasts anything.

            Args:
                token: Contract address of the ERC20 token in the pair. The
                    other side of the pair is always this toolkit's
                    configured native-wrapped token.
                lp_amount: The amount of LP tokens to burn, in whole units
                    (e.g. 0.5).
                from_address: The address that will sign this transaction and
                    that currently holds the LP tokens -- also the recipient
                    of the token and the native asset unless recipient is
                    set.
                recipient: Optional address to receive the token and the
                    native asset. Defaults to from_address.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both
                    amountTokenMin and amountETHMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the withdrawal
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional starting nonce for the plan (EOA mode only;
                    ignored in calls mode). If omitted, the current pending
                    transaction count for from_address is used. The
                    approval call gets this nonce; the withdrawal gets the
                    next one.
            """
            native_wrapped = toolkit._require_native_wrapped()
            pair = toolkit._pair(token, native_wrapped)
            lp_decimals = pair.functions.decimals().call()
            liquidity_base = toolkit._to_base_units(lp_amount, lp_decimals)
            if toolkit.preflight:
                toolkit._require_lp_balance(
                    pair,
                    liquidity_base,
                    from_address,
                    decimals=lp_decimals,
                    purpose="this withdrawal",
                )
            expected_token_base, expected_eth_base = toolkit._lp_redemption_base(
                pair, token, liquidity_base
            )
            decimals_token = toolkit._decimals(token)

            amount_token_min = (
                expected_token_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_eth_min = (
                expected_eth_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            to = Web3.to_checksum_address(recipient or from_address)

            leading, _trailing = toolkit._approval_calls(
                toolkit.router.address,
                [(pair, liquidity_base, f"{lp_amount} LP tokens for {token}/native asset")],
            )
            action = toolkit._call(
                toolkit.router,
                "removeLiquidityETH",
                [
                    Web3.to_checksum_address(token),
                    liquidity_base,
                    amount_token_min,
                    amount_eth_min,
                    to,
                    toolkit._deadline(deadline_secs),
                ],
                role="remove_liquidity",
                description=f"Remove {lp_amount} LP tokens for {token}/native asset",
            )

            return toolkit._plan(
                [*leading, action],
                from_address=from_address,
                summary={
                    "token": token,
                    "lp_amount": lp_amount,
                    "expected_token": expected_token_base / 10**decimals_token,
                    "expected_eth": expected_eth_base / 10**18,
                    "amount_token_min": amount_token_min / 10**decimals_token,
                    "amount_eth_min": amount_eth_min / 10**18,
                },
                nonce=nonce,
            )

        return [
            get_quote_in,
            get_quote_out,
            get_pool_quote,
            get_lp_amounts,
            get_liquidity_token_balance,
            is_token_balance_sufficient,
            is_native_balance_sufficient,
            is_derived_token_input_sufficient,
            is_derived_native_input_sufficient,
            is_liquidity_sufficient,
            is_liquidity_sufficient_eth,
            is_liquidity_removal_sufficient,
            approve_token,
            swap_exact_tokens_for_tokens,
            swap_tokens_for_exact_tokens,
            swap_exact_eth_for_tokens,
            swap_eth_for_exact_tokens,
            swap_exact_tokens_for_eth,
            swap_tokens_for_exact_eth,
            add_liquidity,
            add_liquidity_eth,
            remove_liquidity,
            remove_liquidity_eth,
        ]
