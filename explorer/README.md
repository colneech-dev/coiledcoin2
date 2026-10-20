# CoiledCoin II block explorer

A small web explorer for a CLC2 node. One Python file, standard library only (Python 3.8+), no database.
It reads your own `coiledcoin2d` over RPC, so it always matches what your node has validated.

## Pages

- **Home**: latest blocks (with merge-mined / direct), height, difficulty, network hashrate, peers
- **Block**: header details, coinbase output, fees, AuxPoW parent block, paged transactions
- **Transaction**: inputs, outputs, fee, confirmations
- **Address**: balance and unspent outputs
- **Search**: block height, block hash, txid or address

## Node setup

Add to `coiledcoin2.conf` (see the main README for its location), then restart the node:

```
server=1
txindex=1
```

`txindex=1` is needed to look up old transactions by txid. Enabling it on an existing node re-indexes the chain.
RPC listens on `127.0.0.1:8371` by default.

## Run

```
python explorer.py
```

It finds the node's `.cookie` in the data directory automatically. Open http://127.0.0.1:8080/.
Otherwise pass credentials with `--rpcuser`/`--rpcpassword` (or `CLC2_RPC_USER`/`CLC2_RPC_PASSWORD`),
and use `--datadir`, `--rpc-url`, `--host` and `--port` to change locations.

## Limitations

- **No spent history for addresses.** Bitcoin Core has no address index, so the address page shows the
  current balance and unspent outputs (via `scantxoutset`), not past transactions. Scans can take a
  few seconds and run one at a time; results are cached for 60 seconds. Add an address index
  (e.g. electrs) if you need full history.
- **Public hosting.** The explorer is read-only and never exposes RPC, but put it behind a reverse proxy
  (nginx/Caddy) with HTTPS and rate limiting before binding to `0.0.0.0`. The address page is the
  expensive endpoint, so limit it.
