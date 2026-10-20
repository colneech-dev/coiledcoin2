# CoiledCoin II block explorer

A web explorer and JSON API for a CLC2 node. One Python file, standard library only (Python 3.8+).
It reads your own `coiledcoin2d` over RPC and keeps a SQLite address index, so it always matches
what your node has validated.

## Pages

- **Home**: latest blocks (merge-mined or direct), height, difficulty, network hashrate, peers
- **Block**: header details, coinbase output, fees, AuxPoW parent block, paged transactions
- **Transaction**: inputs, outputs, fee, confirmations
- **Address**: balance, transaction count and full history
- **Mempool**: pending transactions
- **Richlist**: top 100 addresses by balance
- **Search**: block height, block hash, txid or address

## JSON API

All endpoints are read-only and send `Access-Control-Allow-Origin: *`. Amounts are in CLC2.

| Endpoint | Returns |
|---|---|
| `/api/info` | chain, height, difficulty, hashrate, peers, index progress |
| `/api/block/<height or hash>` | node `getblock` output (verbosity 1) |
| `/api/tx/<txid>` | node `getrawtransaction` output (verbosity 2) |
| `/api/address/<address>?page=N` | balance, tx count, 25 history rows per page |
| `/api/mempool` | count, bytes, newest 100 transactions |
| `/api/richlist` | top 100 balances and total |

## Node setup

Add to `coiledcoin2.conf`, then restart the node:

```
server=1
txindex=1
```

The node must not be pruned: the indexer reads `getblock` verbosity 3, which needs undo data.
RPC listens on `127.0.0.1:8371` by default.

## Run

```
python explorer.py
```

Open http://127.0.0.1:8080/. It finds the node's `.cookie` in the data directory, or use
`--rpcuser`/`--rpcpassword` (or `CLC2_RPC_USER`/`CLC2_RPC_PASSWORD`). Other options: `--datadir`,
`--rpc-url`, `--db` (default `explorer.db`), `--host`, `--port`.

On first start the indexer walks the whole chain in the background; pages work meanwhile and show
a "catching up" note. It follows new blocks every 5 seconds and rolls back on reorgs.

### Docker

```
docker build -t clc2-explorer .
docker run -d -p 8080:8080 -v clc2-explorer:/data \
  -e CLC2_RPC_USER=... -e CLC2_RPC_PASSWORD=... clc2-explorer --rpc-url http://host.docker.internal:8371/
```

The node must accept the container's connection: set `rpcbind`/`rpcallowip` for the Docker network
in `coiledcoin2.conf` (never expose RPC publicly).

### systemd

Copy `explorer.py` to `/opt/clc2-explorer/`, `deploy/clc2-explorer.service` to `/etc/systemd/system/`,
put the two `CLC2_RPC_*` variables in `/etc/clc2-explorer.env` (mode 600), then
`systemctl enable --now clc2-explorer`.

## Using it from Miningcore

In the CLC2 entry of Miningcore's `coins.json`:

```json
"explorerBlockLink": "https://explorer.example.com/block/$hash$",
"explorerTxLink": "https://explorer.example.com/tx/{0}",
"explorerAccountLink": "https://explorer.example.com/address/{0}"
```

`/block/` accepts either a hash or a height, so `$height$` works too.

## Notes

- The richlist share is relative to coins held at addresses; outputs without an address (e.g. OP_RETURN) are excluded.
- Put it behind a reverse proxy with HTTPS and rate limiting before binding to `0.0.0.0`.
