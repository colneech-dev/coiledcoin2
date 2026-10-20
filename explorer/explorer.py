#!/usr/bin/env python3
"""CoiledCoin II block explorer.

Single-file, standard-library-only web app that reads a local coiledcoin2d over
JSON-RPC and serves server-rendered pages. See README.md.
"""
import argparse
import base64
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TICKER = "CLC2"
PAGE_TXS = 25
HOME_BLOCKS = 20
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
ADDR = re.compile(r"^[A-Za-z0-9]{26,90}$")


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Rpc:
    def __init__(self, url, auth):
        self.url = url
        self.auth = auth

    def call(self, method, *params):
        body = json.dumps({"jsonrpc": "1.0", "id": "explorer", "method": method, "params": list(params)}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json", "Authorization": "Basic " + self.auth()})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            data = e.read()
        except urllib.error.URLError as e:
            raise RpcError(-1, "cannot reach node: %s" % e.reason)
        reply = json.loads(data, parse_float=Decimal)
        if reply.get("error"):
            raise RpcError(reply["error"]["code"], reply["error"]["message"])
        return reply["result"]


class TtlCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def get(self, key, ttl, fn):
        now = time.monotonic()
        with self.lock:
            hit = self.items.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = fn()
        with self.lock:
            if len(self.items) > 500:
                self.items.clear()
            self.items[key] = (now, value)
        return value


# ---------------------------------------------------------------- formatting

def esc(s):
    return html.escape(str(s), quote=True)


def amount(v):
    return "%s %s" % (format(Decimal(v), ",.8f").rstrip("0").rstrip(".") if Decimal(v) != 0 else "0", TICKER)


def when(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ago(ts):
    d = max(0, int(time.time() - ts))
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if d >= size:
            return "%d%s ago" % (d // size, unit)
    return "%ds ago" % d


def short(h, n=10):
    return h if len(h) <= 2 * n + 1 else h[:n] + "…" + h[-n:]


def hashrate(h):
    for unit in ("H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"):
        if h < 1000:
            return "%.2f %s" % (h, unit)
        h /= 1000
    return "%.2f ZH/s" % h


def link_block(h, label=None):
    return '<a href="/block/%s">%s</a>' % (esc(h), esc(label if label is not None else short(h)))


def link_tx(t):
    return '<a href="/tx/%s">%s</a>' % (esc(t), esc(short(t)))


def link_addr(a):
    return '<a href="/address/%s">%s</a>' % (esc(a), esc(a))


STYLE = """
:root{--bg:#f6f7f9;--fg:#1c2230;--mut:#667085;--card:#fff;--line:#e3e6ec;--acc:#2f6fed}
@media(prefers-color-scheme:dark){:root{--bg:#10141c;--fg:#e6e9f0;--mut:#8b93a5;--card:#181d28;--line:#283042;--acc:#6b9bff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header{background:var(--card);border-bottom:1px solid var(--line)}
.wrap{max-width:1000px;margin:0 auto;padding:0 16px}
.bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:12px 0}
.bar .brand{font-weight:700;font-size:18px;color:var(--fg)}
.bar form{flex:1;min-width:220px;display:flex;gap:8px}
input[type=text]{flex:1;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
button{padding:8px 14px;border:0;border-radius:6px;background:var(--acc);color:#fff;font:inherit;cursor:pointer}
main{padding:20px 0 40px}
h1{font-size:22px;margin:0 0 16px}h2{font-size:17px;margin:24px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.card .v{font-size:18px;font-weight:600;word-break:break-word}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:13px;width:1%;white-space:nowrap}
tr:last-child th,tr:last-child td{border-bottom:0}
.list th{width:auto}.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px;word-break:break-all}
.num{text-align:right}.mut{color:var(--mut)}.pill{display:inline-block;padding:0 8px;border-radius:99px;background:var(--line);font-size:12px}
.io{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:700px){.io{grid-template-columns:1fr}}
.tx{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:12px}
.tx .head{margin-bottom:8px}.pager{display:flex;justify-content:space-between;margin:12px 0}
.err{background:var(--card);border:1px solid #d9534f;border-radius:8px;padding:14px}
footer{color:var(--mut);font-size:13px;padding-bottom:30px}
"""


def page(title, body, q=""):
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s · CoiledCoin II Explorer</title>
<style>%s</style></head><body>
<header><div class="wrap bar"><a class="brand" href="/">CoiledCoin II Explorer</a>
<form action="/search" method="get"><input type="text" name="q" value="%s" placeholder="Block height, block hash, txid or address" autocomplete="off"><button>Search</button></form>
</div></header><main class="wrap">%s</main>
<footer class="wrap">CoiledCoin II (%s) · merge-mined with Bitcoin, chain ID 16</footer></body></html>""" % (esc(title), STYLE, esc(q), body, TICKER)


def kv(rows):
    return "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"


# ---------------------------------------------------------------- pages

class Explorer:
    def __init__(self, rpc):
        self.rpc = rpc
        self.cache = TtlCache()
        self.scan_lock = threading.Lock()

    def block_header(self, key):
        return self.cache.get(("hdr", key), 30, lambda: self.rpc.call("getblockheader", key))

    def home(self):
        info = self.rpc.call("getblockchaininfo")
        mining = self.cache.get("mining", 30, lambda: self.rpc.call("getmininginfo"))
        peers = self.rpc.call("getconnectioncount")
        tip = info["blocks"]
        rows = []
        for h in range(tip, max(-1, tip - HOME_BLOCKS), -1):
            bh = self.rpc.call("getblockhash", h)
            hdr = self.block_header(bh)
            rows.append("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td class=mono>%s</td></tr>" % (
                link_block(bh, str(h)), esc(ago(hdr["time"])), hdr["nTx"],
                '<span class="pill">merge-mined</span>' if hdr.get("auxpow") else '<span class="pill">direct</span>',
                esc(short(bh, 12))))
        cards = [("Height", "{:,}".format(tip)), ("Difficulty", "{:,.0f}".format(info["difficulty"])),
                 ("Network hashrate", hashrate(float(mining.get("networkhashps", 0)))),
                 ("Peers", peers), ("Chain", info["chain"])]
        body = "<h1>Latest blocks</h1><div class=cards>%s</div>" % "".join(
            '<div class=card><div class=k>%s</div><div class=v>%s</div></div>' % (k, esc(v)) for k, v in cards)
        if info.get("initialblockdownload"):
            body += '<p class=err>The node is still syncing (%.2f%%). Data may be incomplete.</p>' % (info["verificationprogress"] * 100)
        body += "<table class=list><tr><th>Height</th><th>Age</th><th>Txs</th><th>Mined</th><th>Hash</th></tr>%s</table>" % "".join(rows)
        return page("Home", body)

    def resolve_block(self, key):
        if re.fullmatch(r"\d{1,9}", key):
            return self.rpc.call("getblockhash", int(key))
        if HEX64.match(key):
            return key.lower()
        raise RpcError(-8, "not a block height or hash")

    def block(self, key, pg):
        bh = self.resolve_block(key)
        blk = self.rpc.call("getblock", bh, 2)
        txs = blk["tx"]
        pages = max(1, (len(txs) + PAGE_TXS - 1) // PAGE_TXS)
        pg = min(max(pg, 1), pages)
        cb = txs[0]
        reward = sum(Decimal(o["value"]) for o in cb["vout"])
        fees = sum(Decimal(t.get("fee", 0)) for t in txs[1:])
        rows = [
            ("Height", "{:,}".format(blk["height"])),
            ("Hash", '<span class=mono>%s</span>' % esc(blk["hash"])),
            ("Time", "%s (%s)" % (esc(when(blk["time"])), esc(ago(blk["time"])))),
            ("Confirmations", "{:,}".format(blk["confirmations"])),
            ("Previous block", link_block(blk["previousblockhash"], blk["previousblockhash"]) if "previousblockhash" in blk else "–"),
            ("Next block", link_block(blk["nextblockhash"], blk["nextblockhash"]) if "nextblockhash" in blk else "–"),
            ("Transactions", len(txs)),
            ("Coinbase output", amount(reward)),
            ("Fees", amount(fees)),
            ("Difficulty", "{:,.2f}".format(blk["difficulty"])),
            ("Bits", esc(blk["bits"])),
            ("Merkle root", '<span class=mono>%s</span>' % esc(blk["merkleroot"])),
            ("Size", "{:,} bytes · weight {:,}".format(blk["size"], blk["weight"])),
            ("Version", esc(blk["versionHex"])),
        ]
        aux = blk.get("auxpow")
        if aux:
            parent = aux.get("parentblock") or {}
            rows.append(("Mining", "Merge-mined (AuxPoW)"))
            if isinstance(parent, dict) and parent.get("hash"):
                rows.append(("Parent block hash", '<span class=mono>%s</span>' % esc(parent["hash"])))
                rows.append(("Parent block time", esc(when(parent["time"]))))
            rows.append(("Parent coinbase tx", '<span class=mono>%s</span>' % esc(aux["tx"]["txid"])))
        else:
            rows.append(("Mining", "Direct (no AuxPoW)"))
        body = "<h1>Block %s</h1>%s<h2>Transactions</h2>" % (esc(blk["height"]), kv(rows))
        for t in txs[(pg - 1) * PAGE_TXS: pg * PAGE_TXS]:
            body += self.tx_card(t)
        if pages > 1:
            prev = '<a href="/block/%s?page=%d">← Newer txs</a>' % (esc(bh), pg - 1) if pg > 1 else "<span></span>"
            nxt = '<a href="/block/%s?page=%d">Older txs →</a>' % (esc(bh), pg + 1) if pg < pages else "<span></span>"
            body += '<div class=pager>%s<span class=mut>Page %d of %d</span>%s</div>' % (prev, pg, pages, nxt)
        return page("Block %s" % blk["height"], body)

    def tx_card(self, t, show_conf=False):
        def out_row(o):
            spk = o["scriptPubKey"]
            who = link_addr(spk["address"]) if "address" in spk else '<span class=mut>%s</span>' % esc(spk.get("type", "script"))
            return "<tr><td>%s</td><td class=num>%s</td></tr>" % (who, esc(amount(o["value"])))

        def in_row(i):
            if "coinbase" in i:
                return "<tr><td><span class=pill>coinbase</span></td><td></td></tr>"
            prev = i.get("prevout")
            if prev:
                spk = prev["scriptPubKey"]
                who = link_addr(spk["address"]) if "address" in spk else esc(spk.get("type", "script"))
                return "<tr><td>%s</td><td class=num>%s</td></tr>" % (who, esc(amount(prev["value"])))
            return "<tr><td>%s:%d</td><td></td></tr>" % (link_tx(i["txid"]), i["vout"])

        ins = "".join(in_row(i) for i in t["vin"][:50])
        if len(t["vin"]) > 50:
            ins += '<tr><td class=mut>… %d more inputs</td><td></td></tr>' % (len(t["vin"]) - 50)
        outs = "".join(out_row(o) for o in t["vout"][:50])
        if len(t["vout"]) > 50:
            outs += '<tr><td class=mut>… %d more outputs</td><td></td></tr>' % (len(t["vout"]) - 50)
        fee = " · fee %s" % esc(amount(t["fee"])) if "fee" in t else ""
        return '<div class=tx><div class=head><span class=mono>%s</span><span class=mut>%s</span></div><div class=io><table>%s</table><table>%s</table></div></div>' % (
            link_tx(t["txid"]), fee, ins, outs)

    def tx(self, txid):
        if not HEX64.match(txid):
            raise RpcError(-8, "invalid txid")
        try:
            t = self.rpc.call("getrawtransaction", txid, 2)
        except RpcError as e:
            if e.code == -5:
                raise RpcError(-5, "Transaction not found. The node needs txindex=1 to look up confirmed transactions.")
            raise
        rows = [("Txid", '<span class=mono>%s</span>' % esc(t["txid"]))]
        if "blockhash" in t:
            rows += [("Block", link_block(t["blockhash"], t["blockhash"])),
                     ("Confirmations", "{:,}".format(t.get("confirmations", 0))),
                     ("Time", esc(when(t["blocktime"])))]
        else:
            rows.append(("Status", "Unconfirmed (in mempool)"))
        rows += [("Size", "%d bytes · %d vbytes · weight %d" % (t["size"], t["vsize"], t["weight"]))]
        if "fee" in t:
            rows.append(("Fee", amount(t["fee"])))
        body = "<h1>Transaction</h1>%s<h2>Inputs and outputs</h2>%s" % (kv(rows), self.tx_card(t))
        return page("Transaction " + short(t["txid"]), body)

    def address(self, addr):
        if not ADDR.match(addr):
            raise RpcError(-8, "invalid address")
        valid = self.rpc.call("validateaddress", addr)
        if not valid["isvalid"]:
            raise RpcError(-5, "Not a valid %s address." % TICKER)

        def scan():
            with self.scan_lock:  # scantxoutset allows one scan at a time
                return self.rpc.call("scantxoutset", "start", ["addr(%s)" % addr])
        res = self.cache.get(("addr", addr), 60, scan)
        utxos = sorted(res.get("unspents", []), key=lambda u: -u["height"])
        rows = [("Address", '<span class=mono>%s</span>' % esc(addr)),
                ("Balance", amount(res["total_amount"])),
                ("Unspent outputs", len(utxos)),
                ("Scanned at height", "{:,}".format(res.get("height", 0)))]
        trs = "".join("<tr><td>%s:%d</td><td>%s</td><td class=num>%s</td></tr>" % (
            link_tx(u["txid"]), u["vout"], link_block(self.rpc.call("getblockhash", u["height"]), str(u["height"])), esc(amount(u["amount"])))
            for u in utxos[:200])
        body = "<h1>Address</h1>%s<h2>Unspent outputs</h2><table class=list><tr><th>Output</th><th>Height</th><th class=num>Amount</th></tr>%s</table>" % (
            kv(rows), trs or "<tr><td colspan=3 class=mut>None</td></tr>")
        body += "<p class=mut>Balances come from the node's UTXO set. Spent history is not indexed.</p>"
        if len(utxos) > 200:
            body += "<p class=mut>Showing the 200 newest of %d outputs.</p>" % len(utxos)
        return page("Address " + short(addr), body)

    def search(self, q):
        q = q.strip()
        if re.fullmatch(r"\d{1,9}", q):
            return "/block/" + q
        if HEX64.match(q):
            try:
                self.rpc.call("getblockheader", q)
                return "/block/" + q.lower()
            except RpcError:
                return "/tx/" + q.lower()
        if ADDR.match(q):
            return "/address/" + q
        raise RpcError(-8, "Nothing matches that. Try a block height, block hash, txid or address.")


def make_handler(ex):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
            try:
                if u.path == "/":
                    return self.send(200, ex.home())
                if parts[0] == "block" and len(parts) == 2:
                    pg = int(qs.get("page", ["1"])[0]) if qs.get("page", ["1"])[0].isdigit() else 1
                    return self.send(200, ex.block(parts[1], pg))
                if parts[0] == "tx" and len(parts) == 2:
                    return self.send(200, ex.tx(parts[1]))
                if parts[0] == "address" and len(parts) == 2:
                    return self.send(200, ex.address(parts[1]))
                if parts[0] == "search":
                    return self.send(302, "", extra={"Location": ex.search(qs.get("q", [""])[0])})
                self.send(404, page("Not found", '<div class=err>Page not found.</div>'))
            except RpcError as e:
                self.send(404 if e.code in (-5, -8) else 502, page("Error", '<div class=err>%s</div>' % esc(e)))
            except Exception as e:  # keep the server alive; log the detail
                sys.stderr.write("error handling %s: %r\n" % (self.path, e))
                self.send(500, page("Error", '<div class=err>Internal error.</div>'))

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def default_datadir():
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "CoiledCoin2")
    return os.path.expanduser("~/.coiledcoin2")


def make_auth(args):
    user = args.rpcuser or os.environ.get("CLC2_RPC_USER")
    pw = args.rpcpassword or os.environ.get("CLC2_RPC_PASSWORD")
    if user and pw:
        token = base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
        return lambda: token
    cookie = os.path.join(args.datadir, ".cookie")  # re-read each call: the cookie changes on node restart

    def from_cookie():
        with open(cookie, "rb") as f:
            return base64.b64encode(f.read().strip()).decode()
    return from_cookie


def main():
    p = argparse.ArgumentParser(description="CoiledCoin II block explorer")
    p.add_argument("--rpc-url", default="http://127.0.0.1:8371/")
    p.add_argument("--rpcuser")
    p.add_argument("--rpcpassword")
    p.add_argument("--datadir", default=default_datadir(), help="used to find .cookie when no rpcuser/rpcpassword is given")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    ex = Explorer(Rpc(args.rpc_url, make_auth(args)))
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(ex))
    print("Explorer on http://%s:%d/ (node %s)" % (args.host, args.port, args.rpc_url))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
