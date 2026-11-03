"""Tunable knobs. Edit here rather than in the pipeline code."""

# Conference / education channels used as a trusted seed corpus. A seed alone does not put a
# video in the catalog: it marks the video as a conference talk and gives a small prior.
SEED_CHANNELS = {
    "@EthereumFoundation": "Devcon / Ethereum Foundation",
    "@ETHGlobal": "ETHGlobal",
    "@solana": "Solana / Breakpoint",
    "@polkadotnetwork": "Polkadot",
    "@paritytech": "Parity / Sub0",
    "@zeroknowledgefm": "Zero Knowledge podcast / zkSummit",
}

# Communities. `weight` scales how much one recommendation from that community counts.
# Research forums are where protocol people talk shop; governance forums lean promotional;
# Reddit is the noisiest. All values are guesses to tune once real data is in.
DISCOURSE_FORUMS = {
    "ethresear.ch": 1.0,
    "ethereum-magicians.org": 1.0,
    "research.lido.fi": 0.7,
    "gov.uniswap.org": 0.6,
    "governance.aave.com": 0.6,     # gov.aave.com redirects here
    "forum.arbitrum.foundation": 0.6,
    "gov.optimism.io": 0.6,
    "forum.makerdao.com": 0.6,
    "forum.celestia.org": 0.8,
    "forum.celo.org": 0.6,
    "discuss.ens.domains": 0.6,
    "forum.cosmos.network": 0.6,
    "forum.polkadot.network": 0.6,
    "delvingbitcoin.org": 1.0,
    "forum.solana.com": 0.8,
    "forum.zcashcommunity.com": 0.8,
    "research.anoma.net": 0.9,
    "forum.aztec.network": 0.8,
    "community.starknet.io": 0.8,
    "research.arbitrum.io": 0.8,
    "forums.sui.io": 0.6,
    "forum.aptosfoundation.org": 0.6,
    "gov.near.org": 0.6,
    "forum.polygon.technology": 0.6,
    "forum.zknation.io": 0.6,
    "forum.scroll.io": 0.6,
    "forum.cardano.org": 0.4,      # mostly community chatter; trimmed after review
    "forum.dfinity.org": 0.6,
    "forum.eigenlayer.xyz": 0.6,
    "forum.osmosis.zone": 0.6,
    "forum.stacks.org": 0.6,
}
COMMUNITY_WEIGHT = {**DISCOURSE_FORUMS, "news.ycombinator.com": 0.8, "reddit.com": 0.5, "github.com": 1.0}

# Hacker News (via the Algolia HN API): only comments/stories that match one of these terms.
HN_TERMS = ["ethereum", "zero knowledge", "zk-snark", "zkp", "rollup", "blockchain", "bitcoin",
            "smart contract", "solidity", "cryptocurrency", "defi", "consensus protocol", "mev",
            "solana", "lightning network", "cosmos sdk", "polkadot", "stablecoin", "web3", "crypto"]
REDDIT_SUBS = ["ethereum", "ethdev", "ethfinance", "ethstaker", "zkproofs", "solidity", "defi",
               "CryptoTechnology", "solana", "cosmosnetwork", "Polkadot", "Bitcoin",
               "solanadev", "BitcoinBeginners", "lightningnetwork", "cardano", "algorand",
               "zec", "Monero", "SUI", "Aptos", "nearprotocol", "Chainlink", "CryptoCurrency",
               "web3"]
GITHUB_ORGS = ["ethereum", "flashbots", "paradigmxyz", "OpenZeppelin", "ethereum-optimism", "matter-labs",
               "starkware-libs", "privacy-scaling-explorations", "sigp", "Consensys", "bitcoin",
               "lightning", "solana-labs", "anza-xyz", "cosmos", "paritytech", "MystenLabs",
               "aptos-labs", "celestiaorg", "near", "zcash", "succinctlabs", "risc0", "a16z"]

# Scoring weights from the plan. Proposed starting weights, not validated ones.
WEIGHTS = {
    "credible_recs": 0.30,       # independent recommendations, weighted by author credibility
    "technical_depth": 0.25,     # LLM judgement of the video itself from title/description/context
    "discussion_quality": 0.15,  # recommendations vs criticism in the surrounding discussion
    "longevity": 0.15,           # recommended across several distinct years
    "captions_quality": 0.10,    # proxy: captions available + factual-claims-still-current flag
    "engagement": 0.05,          # likes on the recommending posts (log-scaled), never raw views
}

# Anti-shilling controls
MAX_COMMUNITY_SHARE = 0.6        # no single forum/source may supply more than 60% of rec weight
SELF_PROMO_WEIGHT = 0.25         # a mention that is the author promoting their own talk
PROMOTION_PENALTY = 0.5          # subtracted per promotional mention (in rec-weight units)
BURST_WINDOW_DAYS = 3            # many low-trust accounts posting the same video inside this window
BURST_MIN_ACCOUNTS = 3           #   ...counts as a coordinated push and is collapsed to one mention
SPONSOR_MARKERS = [
    "sponsored by", "use my code", "use code", "referral", "affiliate", "airdrop",
    "price prediction", "100x", "1000x", "not financial advice", "nfa", "presale",
    "giveaway", "join my telegram", "paid promotion",
]

# Topical filter: a video must mention one of these in its title, channel, description or Claude's
# summary. General communities (Hacker News, big community forums) also link plenty of off-topic videos.
# RELEVANCE_TERMS match as whole words (plural allowed); RELEVANCE_NAMES as exact whole words;
# RELEVANCE_PREFIXES match at the start of a word.
# Avoid plain English words (oracle, scroll, cosmos, consensus, token, mining, wallet, layer 2).
RELEVANCE_TERMS = [
    "crypto", "ether", "eth", "zero-knowledge", "zero knowledge", "defi", "decentralized finance",
    "smart contract", "solidity", "evm", "consensus protocol", "consensus algorithm",
    "consensus mechanism", "proof of stake", "proof-of-stake", "proof of work", "proof-of-work", "staking",
    "restaking", "rollup", "mev", "nft", "stablecoin", "web3", "dao", "tokenomics", "governance token",
    "crypto wallet", "hardware wallet", "seed phrase", "recovery phrase", "bitcoin mining",
    "mining pool", "lightning network", "cosmos sdk", "cosmos hub", "cosmos network", "ibc",
    "internet computer", "data availability", "starks", "zk-stark", "move language", "elliptic curve",
    "homomorphic", "multi-party computation", "mpc", "threshold signature", "merkle", "hash function",
    "digital signature", "distributed ledger", "byzantine fault", "cbdc", "sharding", "danksharding",
    "core devs", "eip",
]
# Chain and project names: whole word, no plural (so the film director Solanas is not Solana).
RELEVANCE_NAMES = [
    "satoshi", "solana", "cardano", "plutus", "zcash", "monero", "polkadot", "near protocol", "dfinity",
    "celestia", "avax", "algorand", "tezos", "chainlink", "uniswap", "makerdao", "aave", "lido",
    "arbitrum", "starknet", "starkware", "zksync", "eigenlayer", "aptos", "tendermint", "devcon",
    "ethglobal", "zkstudyclub", "zcon",
]
RELEVANCE_PREFIXES = ["blockchain", "bitcoin", "ethereum", "cryptocurrenc", "cryptograph", "cryptoeconomic",
                      "zk", "snark", "erc-", "eip-"]

# Catalog inclusion
MIN_SCORE = 0.22
MIN_RECOMMENDERS = 1             # at least one independent recommendation (seeds alone don't count)

TOPICS = [
    "Ethereum protocol", "Consensus", "Scaling & L2s", "Zero-knowledge", "Cryptography",
    "MEV", "DeFi mechanisms", "Security & exploits", "Smart contracts", "EVM",
    "Account abstraction", "Governance", "Economics", "Developer tooling", "Privacy",
    "Data availability", "AI x Crypto", "Bitcoin", "Lightning & payments", "Solana", "Cosmos & IBC",
    "Polkadot & Substrate", "Move chains (Sui, Aptos)", "Other L1s", "Interoperability & bridges",
    "Stablecoins", "History & culture", "Markets & trading", "Cardano", "Zcash",
]

# Chain topics are kept only when the video's title, channel or summary names the chain, and added
# when it does. Claude otherwise tends to file any chain's talk under a nearby topic.
CHAIN_TOPICS = {
    "Bitcoin": r"\bbitcoin|\bbtc\b|satoshi",
    "Lightning & payments": r"lightning network|lightning wallet|\blnd\b|\bpayments?\b|remittance",
    "Solana": r"\bsolana\b|firedancer|\banza\b",
    "Cardano": r"cardano|\bada\b|plutus|ouroboros|hoskinson|\biohk?\b|\biog\b|daedalus|yoroi|emurgo|shelley|voltaire|aiken",
    "Zcash": r"zcash|\bzec\b|zcon|halo ?2|orchard|sapling|electric coin|zooko|\bzfnd\b",
    "Polkadot & Substrate": r"polkadot|substrate|parachain|kusama|parity|gavin wood|\bsub0|polkavm",
    "Cosmos & IBC": r"cosmos|\bibc\b|tendermint|cometbft|osmosis|keplr|interchain|devmos",
    "Move chains (Sui, Aptos)": r"\bsui\b|aptos|move language|move smart contract|mysten",
}
# Topics removed (never added) when their signal is missing from the video's title, channel and summary.
TOPIC_REQUIRES = {
    "AI x Crypto": r"\bai\b|artificial intelligence|machine learning|\bllms?\b|\bgpt|neural|\bagents?\b|numerai",
}
# "Ethereum protocol" is dropped unless something about the video (or its forum) points at Ethereum.
ETHEREUM_SIGNAL = (r"ethereum|\beth\b|\bevm\b|\beips?\b|\beip-|\berc-?\d|devcon|vitalik|solidity|beacon chain|casper|"
                   r"danksharding|sharding|rollup|ethglobal|core devs|\bacd[ce]?\b|ethresear\.ch|ethereum-magicians")
# Topics Claude sometimes invents, mapped onto the list above (anything else off-list is dropped).
TOPIC_ALIASES = {
    "smart contracts": "Smart contracts", "staking": "Consensus", "staking & validators": "Consensus",
    "sidechains": "Interoperability & bridges", "oracles": "DeFi mechanisms", "wallets": "Security & exploits",
    "policy & regulation": "Governance", "education": "History & culture", "social": "History & culture",
    "risk": "Economics",
}
