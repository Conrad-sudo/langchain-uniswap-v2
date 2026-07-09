"""
Standalone LangChain toolkit for read-only Uniswap V2 (and V2-fork, e.g.
PancakeSwap) queries.


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

from decimal import Decimal

from langchain_core.tools import ToolException, tool
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from .abis import erc20_abi, factory_abi, pair_abi, router_abi
from .networks import KNOWN_NETWORKS


class UniswapV2Toolkit:
    """
    Bind once to an RPC endpoint, router, and (optionally) factory/native-wrapped
    token, then call get_tools() to get LangChain tools scoped to that
    deployment. All tool arguments are plain contract addresses and amounts --
    no ticker registry or wallet state is required.

    Deliberately read-only for now. Planned extension point for a future
    write-capable version (not yet implemented -- see summary.md #7):

        def __init__(self, ..., signer=None):
            self.signer = signer  # duck-typed, e.g. sign_and_send(tx_dict) -> tx_hash

    `signer` would stay optional and wallet-agnostic on purpose -- a raw
    eth_account local key, a KMS-backed signer, and an ERC-4337 session-key
    signer (like the one this toolkit was originally extracted from) should
    all be able to satisfy the same duck-typed interface, so the toolkit
    itself never commits to one wallet architecture.

    get_tools() would only include write tools (swap execution, add/remove
    liquidity) when self.signer is set:

        if self.signer:
            tools.extend([swap_exact_tokens_for_tokens, add_liquidity, ...])

    That makes capability structural rather than exception-based -- an agent
    built from a signer-less toolkit never sees a write tool to hallucinate
    calling in the first place. Write tools would require explicit slippage
    (amountOutMin/amountInMax) and deadline arguments so a call can't omit
    them; actual spend-limit enforcement would stay outside this toolkit's
    responsibility, living in the signer or a wrapping policy layer, the same
    split session-key-infra used.
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

            try:
                amounts = toolkit.router.functions.getAmountsIn(amount_out_base, path).call()
            except ContractLogicError as err:
                raise ToolException(
                    f"No Uniswap V2 liquidity path found for {token_in} -> "
                    f"{token_out}. The pool may not exist or have insufficient "
                    f"reserves."
                ) from err

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

            try:
                amounts = toolkit.router.functions.getAmountsOut(amount_in_base, path).call()
            except ContractLogicError as err:
                raise ToolException(
                    f"No Uniswap V2 liquidity path found for {token_in} -> "
                    f"{token_out}. The pool may not exist or have insufficient "
                    f"reserves."
                ) from err

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
            pair = toolkit._pair(token_a, token_b)
            decimals_a = toolkit._decimals(token_a)
            decimals_b = toolkit._decimals(token_b)
            amount_a_base = toolkit._to_base_units(amount_a, decimals_a)

            reserve0, reserve1, _ = pair.functions.getReserves().call()
            token0 = pair.functions.token0().call()
            if token0.lower() == Web3.to_checksum_address(token_a).lower():
                reserve_a, reserve_b = reserve0, reserve1
            else:
                reserve_a, reserve_b = reserve1, reserve0

            amount_b_desired_base = toolkit.router.functions.quote(
                amount_a_base, reserve_a, reserve_b
            ).call()

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

            reserve0, reserve1, _ = pair.functions.getReserves().call()
            total_supply = pair.functions.totalSupply().call()
            token0 = pair.functions.token0().call()

            raw0 = (liquidity * reserve0) // total_supply
            raw1 = (liquidity * reserve1) // total_supply

            if token0.lower() == Web3.to_checksum_address(token_a).lower():
                expected_a_base, expected_b_base = raw0, raw1
            else:
                expected_a_base, expected_b_base = raw1, raw0

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

        return [
            get_quote_in,
            get_quote_out,
            get_pool_quote,
            get_lp_amounts,
            get_liquidity_token_balance,
        ]
