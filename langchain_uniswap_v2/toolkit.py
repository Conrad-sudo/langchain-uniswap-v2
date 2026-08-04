"""
Standalone LangChain toolkit for Uniswap V2 (and V2-fork, e.g. PancakeSwap)
queries plus unsigned write transactions.


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

from langchain_core.tools import ToolException, tool
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from .abis import erc20_abi, factory_abi, pair_abi, router_abi
from .networks import KNOWN_NETWORKS

# Basis-point denominator for slippage math (e.g. 50 bps = 0.5%).
BPS_DENOMINATOR = 10_000
DEFAULT_SLIPPAGE_BPS = 50
DEFAULT_SWAP_DEADLINE_SECS = 600


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
      that build and return an *unsigned* transaction dict -- they never
      hold a private key, sign anything, or submit anything to the network.
      Every write tool takes an explicit from_address (whose transaction
      count/nonce is read to build the tx) and returns a plain dict the
      caller signs and broadcasts with their own wallet, however that's
      implemented. This toolkit intentionally has no concept of a signer or
      wallet: the same instance works identically for an agent driving a
      local eth_account key, a KMS-backed signer, or a smart-contract
      wallet, because it never needs to know which one it's talking to.

    Because approve and act are always separate transactions here (there's
    no session-key-style atomic batching to lean on), a caller preparing a
    swap or a liquidity deposit generally needs approve_token's returned tx
    submitted first. All amount-based write tools also take slippage_bps
    (basis points, default 50) and derive amountOutMin/amountInMax/*Min from
    a live on-chain quote, and deadline_secs (default 600) for the tx's
    on-chain expiry -- both are always explicit tool arguments, never
    silently omitted.
    """

    def __init__(
        self,
        rpc_url: str,
        router_address: str,
        factory_address: str | None = None,
        native_wrapped_address: str | None = None,
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

        self._erc20_abi = erc20_abi
        self._pair_abi = pair_abi
        self._erc20_cache: dict[str, Contract] = {}
        self._pair_cache: dict[tuple[str, str], Contract] = {}

    @classmethod
    def for_chain(cls, chain_id: int, rpc_url: str | None = None) -> UniswapV2Toolkit:
        """
        Convenience constructor for chains in KNOWN_NETWORKS -- looks up the
        router, factory, and native-wrapped-token addresses for chain_id so
        callers only need to supply a chain_id.

        Args:
            chain_id: The EVM chain ID (e.g. 1 for Ethereum mainnet, 56 for BSC).
            rpc_url: Optional RPC endpoint override. If omitted, falls back to
                KNOWN_NETWORKS' public endpoint for that chain -- fine for
                prototyping, but rate-limited; pass your own for production.

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
        liquidity_base LP tokens, via the proportional share formula."""
        reserve0, reserve1, _ = pair.functions.getReserves().call()
        total_supply = pair.functions.totalSupply().call()
        token0 = pair.functions.token0().call()

        raw0 = (liquidity_base * reserve0) // total_supply
        raw1 = (liquidity_base * reserve1) // total_supply

        if token0.lower() == Web3.to_checksum_address(token_a).lower():
            return raw0, raw1
        return raw1, raw0

    def _build_path(self, token_in: str, token_out: str) -> list[str]:
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        if (
            self.native_wrapped_address
            and token_in != self.native_wrapped_address
            and token_out != self.native_wrapped_address
        ):
            return [token_in, self.native_wrapped_address, token_out]
        return [token_in, token_out]

    def _build_unsigned_tx(
        self,
        contract_function,
        from_address: str,
        value: int = 0,
        nonce: int | None = None,
    ) -> dict:
        """
        Builds (but never signs or sends) a transaction dict for a bound
        contract function call. Only RPC reads are involved -- no private key
        or signer is ever touched. If nonce is omitted, the current pending
        transaction count for from_address is used; pass it explicitly when
        building more than one unsigned transaction in sequence (e.g. an
        approval followed by a swap) so the two don't collide.
        """
        from_address = Web3.to_checksum_address(from_address)
        tx_params = {
            "from": from_address,
            "value": value,
            "nonce": (
                nonce
                if nonce is not None
                else self.w3.eth.get_transaction_count(from_address, "pending")
            ),
            "chainId": self.w3.eth.chain_id,
        }
        try:
            return contract_function.build_transaction(tx_params)
        except ContractLogicError as err:
            raise ToolException(f"Transaction would revert: {err}") from err

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
            balance = (
                toolkit._erc20(token_address)
                .functions.balanceOf(Web3.to_checksum_address(owner_address))
                .call()
            )
            return balance >= toolkit._to_base_units(amount, decimals)

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
            balance = toolkit.w3.eth.get_balance(Web3.to_checksum_address(owner_address))
            return balance >= toolkit._to_base_units(amount, 18)

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
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in=token_in, label_out=token_out
            )
            required_base = amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

            balance = (
                toolkit._erc20(token_in)
                .functions.balanceOf(Web3.to_checksum_address(owner_address))
                .call()
            )

            return {
                "is_sufficient": balance >= required_base,
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
            native_wrapped = toolkit._require_native_wrapped()
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            path = toolkit._build_path(native_wrapped, token_out)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in="the native asset", label_out=token_out
            )
            required_base = amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

            balance = toolkit.w3.eth.get_balance(Web3.to_checksum_address(owner_address))

            return {
                "is_sufficient": balance >= required_base,
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

            owner = Web3.to_checksum_address(owner_address)
            balance_a = toolkit._erc20(token_a).functions.balanceOf(owner).call()
            balance_b = toolkit._erc20(token_b).functions.balanceOf(owner).call()

            is_sufficient = balance_a >= amount_a_base and balance_b >= amount_b_required_base
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

            owner = Web3.to_checksum_address(owner_address)
            balance_token = toolkit._erc20(token).functions.balanceOf(owner).call()
            balance_native = toolkit.w3.eth.get_balance(owner)

            is_sufficient = (
                balance_token >= amount_token_base
                and balance_native >= amount_native_required_base
            )
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
            balance = pair.functions.balanceOf(Web3.to_checksum_address(owner_address)).call()
            return balance >= toolkit._to_base_units(lp_amount, decimals)

        @tool
        def approve_token(
            token_address: str,
            spender_address: str,
            amount: float,
            from_address: str,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned ERC20 approve transaction, authorizing
            spender_address to transfer up to `amount` of token_address on
            behalf of from_address. Required before any swap or liquidity
            tool that needs to pull tokens from from_address -- the router
            (or another spender) needs an allowance first, and this toolkit
            never bundles approval and action into one call.

            This tool never signs or broadcasts anything. It only reads
            on-chain state needed to build the transaction (nonce, chain ID,
            gas) and returns a plain transaction dict for the caller to sign
            and submit with their own wallet.

            Args:
                token_address: Contract address of the token to approve.
                spender_address: Address being granted the allowance --
                    usually this toolkit's router address.
                amount: The amount to approve, in whole units (e.g. 100 for
                    100 tokens, adjusted for that token's decimals
                    internally). Pass a very large number for an
                    effectively-unlimited approval.
                from_address: The address that will sign this transaction --
                    i.e. the current token holder granting the approval.
                nonce: Optional nonce override. If omitted, the current
                    pending transaction count for from_address is used. Pass
                    an explicit value when building multiple unsigned
                    transactions in sequence before submitting any of them
                    (e.g. approve then swap), to avoid nonce collisions.

            Returns:
                An unsigned transaction dict (to, data, value, gas, nonce,
                chainId, etc.) ready to be signed and sent by the caller.
                Nothing is submitted to the network by this tool.
            """
            decimals = toolkit._decimals(token_address)
            amount_base = toolkit._to_base_units(amount, decimals)
            erc20 = toolkit._erc20(token_address)
            fn = erc20.functions.approve(
                Web3.to_checksum_address(spender_address), amount_base
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def swap_exact_tokens_for_tokens(
            token_in: str,
            token_out: str,
            amount_in: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps an exact amount of
            token_in for token_out via the router's
            swapExactTokensForTokens. The router must already hold an
            allowance for at least amount_in of token_in from from_address --
            call approve_token first if it doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token_in: Contract address of the token being sold.
                token_out: Contract address of the token being bought.
                amount_in: The exact amount of token_in to sell, in whole
                    units.
                from_address: The address that will sign this transaction --
                    also the recipient of token_out.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            decimals_in = toolkit._decimals(token_in)
            amount_in_base = toolkit._to_base_units(amount_in, decimals_in)
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in=token_in, label_out=token_out
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapExactTokensForTokens(
                amount_in_base,
                amount_out_min,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def swap_tokens_for_exact_tokens(
            token_in: str,
            token_out: str,
            amount_out: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps as much of token_in as
            needed for an exact amount of token_out via the router's
            swapTokensForExactTokens. The router must already hold an
            allowance for at least the derived amountInMax of token_in from
            from_address -- call approve_token first if it doesn't (a live
            quote via get_quote_in tells you the expected amount before
            adding a slippage buffer).

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token_in: Contract address of the token being sold.
                token_out: Contract address of the token being bought.
                amount_out: The exact amount of token_out to receive, in
                    whole units.
                from_address: The address that will sign this transaction --
                    also the recipient of token_out.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax as the quoted input increased by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            path = toolkit._build_path(token_in, token_out)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in=token_in, label_out=token_out
            )
            amount_in_max = amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapTokensForExactTokens(
                amount_out_base,
                amount_in_max,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def swap_exact_eth_for_tokens(
            token_out: str,
            amount_in: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps an exact amount of the
            chain's native asset (ETH, BNB, etc.) for token_out via the
            router's swapExactETHForTokens. "ETH" in the tool name is a
            generic internal label -- this works identically on every
            supported network. Requires this toolkit to have been configured
            with native_wrapped_address.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict, with the native-asset amount set as the
            tx's value field, for the caller to sign and submit with their
            own wallet.

            Args:
                token_out: Contract address of the token being bought.
                amount_in: The exact amount of the native asset to spend, in
                    whole units (e.g. 1.5).
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of
                    token_out.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            amount_in_base = toolkit._to_base_units(amount_in, 18)
            path = toolkit._build_path(native_wrapped, token_out)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in="the native asset", label_out=token_out
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapExactETHForTokens(
                amount_out_min,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(
                fn, from_address, value=amount_in_base, nonce=nonce
            )

        @tool
        def swap_eth_for_exact_tokens(
            token_out: str,
            amount_out: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps however much of the
            chain's native asset (ETH, BNB, etc.) is needed for an exact
            amount of token_out via the router's swapETHForExactTokens. The
            router refunds any unused native asset to from_address within
            the same on-chain transaction. "ETH" in the tool name is a
            generic internal label -- this works identically on every
            supported network. Requires this toolkit to have been configured
            with native_wrapped_address.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict, with the derived amountInMax set as the
            tx's value field, for the caller to sign and submit with their
            own wallet.

            Args:
                token_out: Contract address of the token being bought.
                amount_out: The exact amount of token_out to receive, in
                    whole units.
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of
                    token_out.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax (the tx value) as the quoted input increased
                    by this percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_out = toolkit._decimals(token_out)
            amount_out_base = toolkit._to_base_units(amount_out, decimals_out)
            path = toolkit._build_path(native_wrapped, token_out)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in="the native asset", label_out=token_out
            )
            amount_in_max = amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapETHForExactTokens(
                amount_out_base,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(
                fn, from_address, value=amount_in_max, nonce=nonce
            )

        @tool
        def swap_exact_tokens_for_eth(
            token_in: str,
            amount_in: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps an exact amount of
            token_in for the chain's native asset (ETH, BNB, etc.) via the
            router's swapExactTokensForETH. "ETH" in the tool name is a
            generic internal label -- this works identically on every
            supported network. Requires this toolkit to have been configured
            with native_wrapped_address. The router must already hold an
            allowance for at least amount_in of token_in from from_address --
            call approve_token first if it doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token_in: Contract address of the token being sold.
                amount_in: The exact amount of token_in to sell, in whole
                    units.
                from_address: The address that will sign this transaction --
                    also the recipient of the native asset.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountOutMin as the quoted output reduced by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_in = toolkit._decimals(token_in)
            amount_in_base = toolkit._to_base_units(amount_in, decimals_in)
            path = toolkit._build_path(token_in, native_wrapped)

            amounts = toolkit._quote_amounts_out(
                amount_in_base, path, label_in=token_in, label_out="the native asset"
            )
            amount_out_min = amounts[-1] * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapExactTokensForETH(
                amount_in_base,
                amount_out_min,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def swap_tokens_for_exact_eth(
            token_in: str,
            amount_out: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that swaps however much of
            token_in is needed for an exact amount of the chain's native
            asset (ETH, BNB, etc.) via the router's swapTokensForExactETH.
            "ETH" in the tool/parameter names is a generic internal label --
            this works identically on every supported network. Requires this
            toolkit to have been configured with native_wrapped_address. The
            router must already hold an allowance for at least the derived
            amountInMax of token_in from from_address -- call approve_token
            first if it doesn't (a live quote via get_quote_in tells you the
            expected amount before adding a slippage buffer).

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live quote, nonce, chain ID, gas) and returns a
            plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token_in: Contract address of the token being sold.
                amount_out: The exact amount of the native asset to receive,
                    in whole units (e.g. 1.5).
                from_address: The address that will sign this transaction --
                    also the recipient of the native asset.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). A live quote is used to derive
                    amountInMax as the quoted input increased by this
                    percentage. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the swap reverts
                    if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            amount_out_base = toolkit._to_base_units(amount_out, 18)
            path = toolkit._build_path(token_in, native_wrapped)

            amounts = toolkit._quote_amounts_in(
                amount_out_base, path, label_in=token_in, label_out="the native asset"
            )
            amount_in_max = amounts[0] * (BPS_DENOMINATOR + slippage_bps) // BPS_DENOMINATOR

            fn = toolkit.router.functions.swapTokensForExactETH(
                amount_out_base,
                amount_in_max,
                path,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def add_liquidity(
            token_a: str,
            token_b: str,
            amount_a: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that adds liquidity to a Uniswap V2
            token/token pool via the router's addLiquidity. The proportional
            token_b amount is derived from live pool reserves via
            get_pool_quote's logic, so the deposit matches the current pool
            ratio. The router must already hold allowances for at least
            amount_a of token_a and the derived amount_b of token_b from
            from_address -- call approve_token for both first if it doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live pool quote, nonce, chain ID, gas) and
            returns a plain transaction dict for the caller to sign and
            submit with their own wallet.

            Args:
                token_a: Contract address of the first token to deposit.
                token_b: Contract address of the second token to deposit.
                amount_a: The desired amount of token_a to deposit, in whole
                    units. The proportional token_b amount is computed from
                    pool reserves automatically.
                from_address: The address that will sign this transaction and
                    that currently holds both tokens -- also the recipient of
                    the LP tokens.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both amountAMin and
                    amountBMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the deposit
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            decimals_a = toolkit._decimals(token_a)
            amount_a_base = toolkit._to_base_units(amount_a, decimals_a)
            amount_b_desired_base = toolkit._quote_deposit_base(
                token_a, token_b, amount_a_base
            )

            amount_a_min = amount_a_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            amount_b_min = (
                amount_b_desired_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )

            fn = toolkit.router.functions.addLiquidity(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b),
                amount_a_base,
                amount_b_desired_base,
                amount_a_min,
                amount_b_min,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def add_liquidity_eth(
            token: str,
            amount_token: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that adds liquidity to a Uniswap V2
            token/native-asset pool via the router's addLiquidityETH. The
            proportional native-asset amount is derived from live pool
            reserves so the deposit matches the current pool ratio. "ETH" in
            the tool name is a generic internal label -- this works
            identically on every supported network. Requires this toolkit to
            have been configured with native_wrapped_address. The router
            must already hold an allowance for at least amount_token of
            token from from_address -- call approve_token first if it
            doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (a live pool quote, nonce, chain ID, gas) and
            returns a plain transaction dict, with the derived native-asset
            amount set as the tx's value field, for the caller to sign and
            submit with their own wallet.

            Args:
                token: Contract address of the ERC20 token to deposit
                    alongside the native asset.
                amount_token: The desired amount of token to deposit, in
                    whole units. The proportional native-asset amount is
                    computed from pool reserves automatically.
                from_address: The address that will sign this transaction and
                    send the native-asset value -- also the recipient of the
                    LP tokens.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both
                    amountTokenMin and amountETHMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the deposit
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            decimals_token = toolkit._decimals(token)
            amount_token_base = toolkit._to_base_units(amount_token, decimals_token)
            amount_eth_desired_base = toolkit._quote_deposit_base(
                token, native_wrapped, amount_token_base
            )

            amount_token_min = (
                amount_token_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_eth_min = (
                amount_eth_desired_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )

            fn = toolkit.router.functions.addLiquidityETH(
                Web3.to_checksum_address(token),
                amount_token_base,
                amount_token_min,
                amount_eth_min,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(
                fn, from_address, value=amount_eth_desired_base, nonce=nonce
            )

        @tool
        def remove_liquidity(
            token_a: str,
            token_b: str,
            lp_amount: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that removes liquidity from a
            Uniswap V2 pool via the router's removeLiquidity. Expected return
            amounts for both tokens are derived from live pool reserves using
            the proportional share formula (liquidity * reserve /
            totalSupply). The router must already hold an allowance for at
            least lp_amount of the pair's own LP token from from_address --
            call approve_token with the pair address first if it doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (live reserves, nonce, chain ID, gas) and returns
            a plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token_a: Contract address of the first token in the pair.
                token_b: Contract address of the second token in the pair.
                lp_amount: The amount of LP tokens to burn, in whole units
                    (e.g. 0.5).
                from_address: The address that will sign this transaction and
                    that currently holds the LP tokens -- also the recipient
                    of both returned tokens.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both amountAMin and
                    amountBMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the withdrawal
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            pair = toolkit._pair(token_a, token_b)
            lp_decimals = pair.functions.decimals().call()
            liquidity_base = toolkit._to_base_units(lp_amount, lp_decimals)
            expected_a_base, expected_b_base = toolkit._lp_redemption_base(
                pair, token_a, liquidity_base
            )

            amount_a_min = (
                expected_a_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_b_min = (
                expected_b_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )

            fn = toolkit.router.functions.removeLiquidity(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b),
                liquidity_base,
                amount_a_min,
                amount_b_min,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

        @tool
        def remove_liquidity_eth(
            token: str,
            lp_amount: float,
            from_address: str,
            slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
            deadline_secs: int = DEFAULT_SWAP_DEADLINE_SECS,
            nonce: int | None = None,
        ) -> dict:
            """
            Builds an unsigned transaction that removes liquidity from a
            Uniswap V2 token/native-asset pool via the router's
            removeLiquidityETH. Expected return amounts are derived from live
            pool reserves using the proportional share formula. The router
            unwraps the wrapped-native share to the raw native asset before
            sending it back. "ETH" in the tool/parameter names is a generic
            internal label -- this works identically on every supported
            network. Requires this toolkit to have been configured with
            native_wrapped_address. The router must already hold an
            allowance for at least lp_amount of the pair's own LP token from
            from_address -- call approve_token with the pair address first
            if it doesn't.

            This tool never signs or broadcasts anything. It only reads
            on-chain state (live reserves, nonce, chain ID, gas) and returns
            a plain transaction dict for the caller to sign and submit with
            their own wallet.

            Args:
                token: Contract address of the ERC20 token in the pair. The
                    other side of the pair is always this toolkit's
                    configured native-wrapped token.
                lp_amount: The amount of LP tokens to burn, in whole units
                    (e.g. 0.5).
                from_address: The address that will sign this transaction and
                    that currently holds the LP tokens -- also the recipient
                    of the token and the native asset.
                slippage_bps: Maximum acceptable slippage in basis points
                    (e.g. 50 = 0.5%). Applied downward to both
                    amountTokenMin and amountETHMin. Defaults to 50 bps.
                deadline_secs: Seconds from now after which the withdrawal
                    reverts if not yet mined. Defaults to 600 (10 minutes).
                nonce: Optional nonce override -- see approve_token.

            Returns:
                An unsigned transaction dict ready to be signed and sent by
                the caller. Nothing is submitted to the network by this tool.
            """
            native_wrapped = toolkit._require_native_wrapped()
            pair = toolkit._pair(token, native_wrapped)
            lp_decimals = pair.functions.decimals().call()
            liquidity_base = toolkit._to_base_units(lp_amount, lp_decimals)
            expected_token_base, expected_eth_base = toolkit._lp_redemption_base(
                pair, token, liquidity_base
            )

            amount_token_min = (
                expected_token_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )
            amount_eth_min = (
                expected_eth_base * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR
            )

            fn = toolkit.router.functions.removeLiquidityETH(
                Web3.to_checksum_address(token),
                liquidity_base,
                amount_token_min,
                amount_eth_min,
                Web3.to_checksum_address(from_address),
                toolkit._deadline(deadline_secs),
            )
            return toolkit._build_unsigned_tx(fn, from_address, nonce=nonce)

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
