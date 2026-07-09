router_abi = [
  {
    "type": "function",
    "name": "WETH",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "addLiquidity",
    "inputs": [
      { "name": "tokenA", "type": "address", "internalType": "address" },
      { "name": "tokenB", "type": "address", "internalType": "address" },
      { "name": "amountADesired", "type": "uint256", "internalType": "uint256" },
      { "name": "amountBDesired", "type": "uint256", "internalType": "uint256" },
      { "name": "amountAMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountBMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountA", "type": "uint256", "internalType": "uint256" },
      { "name": "amountB", "type": "uint256", "internalType": "uint256" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "addLiquidityETH",
    "inputs": [
      { "name": "token", "type": "address", "internalType": "address" },
      { "name": "amountTokenDesired", "type": "uint256", "internalType": "uint256" },
      { "name": "amountTokenMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETHMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountToken", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETH", "type": "uint256", "internalType": "uint256" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "payable"
  },
  {
    "type": "function",
    "name": "factory",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "getAmountIn",
    "inputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveIn", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveOut", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "getAmountOut",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveIn", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveOut", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "getAmountsIn",
    "inputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getAmountsOut",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "quote",
    "inputs": [
      { "name": "amountA", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveA", "type": "uint256", "internalType": "uint256" },
      { "name": "reserveB", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountB", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "removeLiquidity",
    "inputs": [
      { "name": "tokenA", "type": "address", "internalType": "address" },
      { "name": "tokenB", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountAMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountBMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountA", "type": "uint256", "internalType": "uint256" },
      { "name": "amountB", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "removeLiquidityETH",
    "inputs": [
      { "name": "token", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountTokenMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETHMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountToken", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETH", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "removeLiquidityETHSupportingFeeOnTransferTokens",
    "inputs": [
      { "name": "token", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountTokenMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETHMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amountETH", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "removeLiquidityETHWithPermit",
    "inputs": [
      { "name": "token", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountTokenMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETHMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" },
      { "name": "approveMax", "type": "bool", "internalType": "bool" },
      { "name": "v", "type": "uint8", "internalType": "uint8" },
      { "name": "r", "type": "bytes32", "internalType": "bytes32" },
      { "name": "s", "type": "bytes32", "internalType": "bytes32" }
    ],
    "outputs": [
      { "name": "amountToken", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETH", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "removeLiquidityETHWithPermitSupportingFeeOnTransferTokens",
    "inputs": [
      { "name": "token", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountTokenMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountETHMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" },
      { "name": "approveMax", "type": "bool", "internalType": "bool" },
      { "name": "v", "type": "uint8", "internalType": "uint8" },
      { "name": "r", "type": "bytes32", "internalType": "bytes32" },
      { "name": "s", "type": "bytes32", "internalType": "bytes32" }
    ],
    "outputs": [
      { "name": "amountETH", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "removeLiquidityWithPermit",
    "inputs": [
      { "name": "tokenA", "type": "address", "internalType": "address" },
      { "name": "tokenB", "type": "address", "internalType": "address" },
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" },
      { "name": "amountAMin", "type": "uint256", "internalType": "uint256" },
      { "name": "amountBMin", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" },
      { "name": "approveMax", "type": "bool", "internalType": "bool" },
      { "name": "v", "type": "uint8", "internalType": "uint8" },
      { "name": "r", "type": "bytes32", "internalType": "bytes32" },
      { "name": "s", "type": "bytes32", "internalType": "bytes32" }
    ],
    "outputs": [
      { "name": "amountA", "type": "uint256", "internalType": "uint256" },
      { "name": "amountB", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapETHForExactTokens",
    "inputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "payable"
  },
  {
    "type": "function",
    "name": "swapExactETHForTokens",
    "inputs": [
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "payable"
  },
  {
    "type": "function",
    "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
    "inputs": [
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [],
    "stateMutability": "payable"
  },
  {
    "type": "function",
    "name": "swapExactTokensForETH",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapExactTokensForTokens",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
    "inputs": [
      { "name": "amountIn", "type": "uint256", "internalType": "uint256" },
      { "name": "amountOutMin", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapTokensForExactETH",
    "inputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" },
      { "name": "amountInMax", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swapTokensForExactTokens",
    "inputs": [
      { "name": "amountOut", "type": "uint256", "internalType": "uint256" },
      { "name": "amountInMax", "type": "uint256", "internalType": "uint256" },
      { "name": "path", "type": "address[]", "internalType": "address[]" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "amounts", "type": "uint256[]", "internalType": "uint256[]" }
    ],
    "stateMutability": "nonpayable"
  }
]


factory_abi = [
  {
    "type": "function",
    "name": "allPairs",
    "inputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "pair", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "allPairsLength",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "createPair",
    "inputs": [
      { "name": "tokenA", "type": "address", "internalType": "address" },
      { "name": "tokenB", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "pair", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "feeTo",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "feeToSetter",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getPair",
    "inputs": [
      { "name": "tokenA", "type": "address", "internalType": "address" },
      { "name": "tokenB", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "pair", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "setFeeTo",
    "inputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setFeeToSetter",
    "inputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "event",
    "name": "PairCreated",
    "inputs": [
      { "name": "token0", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "token1", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "pair", "type": "address", "indexed": False, "internalType": "address" },
      { "name": "", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  }
]


pair_abi = [
  {
    "type": "function",
    "name": "DOMAIN_SEPARATOR",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "bytes32", "internalType": "bytes32" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "MINIMUM_LIQUIDITY",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "PERMIT_TYPEHASH",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "bytes32", "internalType": "bytes32" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "allowance",
    "inputs": [
      { "name": "owner", "type": "address", "internalType": "address" },
      { "name": "spender", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "approve",
    "inputs": [
      { "name": "spender", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "balanceOf",
    "inputs": [
      { "name": "owner", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "burn",
    "inputs": [
      { "name": "to", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "amount0", "type": "uint256", "internalType": "uint256" },
      { "name": "amount1", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "decimals",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint8", "internalType": "uint8" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "factory",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getReserves",
    "inputs": [],
    "outputs": [
      { "name": "reserve0", "type": "uint112", "internalType": "uint112" },
      { "name": "reserve1", "type": "uint112", "internalType": "uint112" },
      { "name": "blockTimestampLast", "type": "uint32", "internalType": "uint32" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "initialize",
    "inputs": [
      { "name": "", "type": "address", "internalType": "address" },
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "kLast",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "mint",
    "inputs": [
      { "name": "to", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "liquidity", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "name",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "string", "internalType": "string" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "nonces",
    "inputs": [
      { "name": "owner", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "permit",
    "inputs": [
      { "name": "owner", "type": "address", "internalType": "address" },
      { "name": "spender", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" },
      { "name": "deadline", "type": "uint256", "internalType": "uint256" },
      { "name": "v", "type": "uint8", "internalType": "uint8" },
      { "name": "r", "type": "bytes32", "internalType": "bytes32" },
      { "name": "s", "type": "bytes32", "internalType": "bytes32" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "price0CumulativeLast",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "price1CumulativeLast",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "skim",
    "inputs": [
      { "name": "to", "type": "address", "internalType": "address" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "swap",
    "inputs": [
      { "name": "amount0Out", "type": "uint256", "internalType": "uint256" },
      { "name": "amount1Out", "type": "uint256", "internalType": "uint256" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "data", "type": "bytes", "internalType": "bytes" }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "symbol",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "string", "internalType": "string" }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "sync",
    "inputs": [],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "token0",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "token1",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "address", "internalType": "address" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "totalSupply",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "transfer",
    "inputs": [
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "transferFrom",
    "inputs": [
      { "name": "from", "type": "address", "internalType": "address" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "event",
    "name": "Approval",
    "inputs": [
      { "name": "owner", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "spender", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "value", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Burn",
    "inputs": [
      { "name": "sender", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "amount0", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "amount1", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "to", "type": "address", "indexed": True, "internalType": "address" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Mint",
    "inputs": [
      { "name": "sender", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "amount0", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "amount1", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Swap",
    "inputs": [
      { "name": "sender", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "amount0In", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "amount1In", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "amount0Out", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "amount1Out", "type": "uint256", "indexed": False, "internalType": "uint256" },
      { "name": "to", "type": "address", "indexed": True, "internalType": "address" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Sync",
    "inputs": [
      { "name": "reserve0", "type": "uint112", "indexed": False, "internalType": "uint112" },
      { "name": "reserve1", "type": "uint112", "indexed": False, "internalType": "uint112" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Transfer",
    "inputs": [
      { "name": "from", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "to", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "value", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  }
]


erc20_abi = [
  {
    "type": "function",
    "name": "allowance",
    "inputs": [
      { "name": "owner", "type": "address", "internalType": "address" },
      { "name": "spender", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "approve",
    "inputs": [
      { "name": "spender", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "balanceOf",
    "inputs": [
      { "name": "account", "type": "address", "internalType": "address" }
    ],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "decimals",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint8", "internalType": "uint8" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "name",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "string", "internalType": "string" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "symbol",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "string", "internalType": "string" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "totalSupply",
    "inputs": [],
    "outputs": [
      { "name": "", "type": "uint256", "internalType": "uint256" }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "transfer",
    "inputs": [
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "transferFrom",
    "inputs": [
      { "name": "from", "type": "address", "internalType": "address" },
      { "name": "to", "type": "address", "internalType": "address" },
      { "name": "value", "type": "uint256", "internalType": "uint256" }
    ],
    "outputs": [
      { "name": "", "type": "bool", "internalType": "bool" }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "event",
    "name": "Approval",
    "inputs": [
      { "name": "owner", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "spender", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "value", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  },
  {
    "type": "event",
    "name": "Transfer",
    "inputs": [
      { "name": "from", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "to", "type": "address", "indexed": True, "internalType": "address" },
      { "name": "value", "type": "uint256", "indexed": False, "internalType": "uint256" }
    ],
    "anonymous": False
  }
]
