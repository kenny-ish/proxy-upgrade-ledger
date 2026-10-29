#!/usr/bin/env python3
"""proxy-upgrade-ledger: rebuild the admin / implementation / beacon history of an
upgradeable proxy from its logs and check it against the live storage slots.

Only JSON-RPC is used (eth_getLogs, eth_getStorageAt, eth_getCode, eth_call,
eth_getBlockByNumber, eth_chainId, eth_blockNumber). Standard library only.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "proxy-upgrade-ledger/0.1 (+https://github.com)"

# ---------------------------------------------------------------------------
# keccak-256 (constants are derived from the spec, not copied from a table)
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


def _rc_bit(t):
    """Bit t of the Keccak round-constant LFSR (polynomial x^8+x^6+x^5+x^4+1)."""
    if t % 255 == 0:
        return 1
    r = 1
    for _ in range(t % 255):
        r <<= 1
        if r & 0x100:
            r ^= 0x171
    return r & 1


def _round_constants():
    out = []
    for i in range(24):
        rc = 0
        for j in range(7):
            rc |= _rc_bit(j + 7 * i) << ((1 << j) - 1)
        out.append(rc)
    return out


def _rotation_offsets():
    rot = [0] * 25
    x, y = 1, 0
    for t in range(24):
        rot[x + 5 * y] = ((t + 1) * (t + 2) // 2) % 64
        x, y = y, (2 * x + 3 * y) % 5
    return rot


_RC = _round_constants()
_ROT = _rotation_offsets()


def _rotl(v, n):
    n %= 64
    if n == 0:
        return v
    return ((v << n) | (v >> (64 - n))) & _MASK64


def _keccak_f(a):
    for rnd in range(24):
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        a = [a[i] ^ d[i % 5] for i in range(25)]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(a[x + 5 * y], _ROT[x + 5 * y])
        a = [
            b[i] ^ ((~b[(i % 5 + 1) % 5 + 5 * (i // 5)]) & b[(i % 5 + 2) % 5 + 5 * (i // 5)])
            for i in range(25)
        ]
        a[0] ^= _RC[rnd]
    return a


def _sponge256(data, pad_byte):
    """Keccak sponge with rate 1088 and a 32-byte output.

    pad_byte 0x01 gives Keccak-256 (Ethereum), 0x06 gives SHA3-256.
    """
    rate = 136
    msg = bytearray(data)
    msg.append(pad_byte)
    while len(msg) % rate:
        msg.append(0x00)
    msg[-1] |= 0x80
    st = [0] * 25
    for off in range(0, len(msg), rate):
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "little")
        st = _keccak_f(st)
    return b"".join(st[i].to_bytes(8, "little") for i in range(4))


def keccak256(data):
    return _sponge256(data, 0x01)


def keccak_hex(data):
    return "0x" + keccak256(data).hex()


def event_topic(signature):
    return keccak_hex(signature.encode())


def selector(signature):
    return "0x" + keccak256(signature.encode())[:4].hex()


# ---------------------------------------------------------------------------
# Known slots and topics
# ---------------------------------------------------------------------------

def eip1967_slot(label):
    return "0x%064x" % ((int.from_bytes(keccak256(label.encode()), "big") - 1) % (1 << 256))


SLOTS = {
    "eip1967.implementation": eip1967_slot("eip1967.proxy.implementation"),
    "eip1967.admin": eip1967_slot("eip1967.proxy.admin"),
    "eip1967.beacon": eip1967_slot("eip1967.proxy.beacon"),
    "zos.implementation": keccak_hex(b"org.zeppelinos.proxy.implementation"),
    "zos.admin": keccak_hex(b"org.zeppelinos.proxy.admin"),
}

TOPIC_UPGRADED = event_topic("Upgraded(address)")
TOPIC_ADMIN_CHANGED = event_topic("AdminChanged(address,address)")
TOPIC_BEACON_UPGRADED = event_topic("BeaconUpgraded(address)")
TOPICS = {
    TOPIC_UPGRADED: "implementation",
    TOPIC_ADMIN_CHANGED: "admin",
    TOPIC_BEACON_UPGRADED: "beacon",
}
SEL_IMPLEMENTATION = selector("implementation()")

ZERO = "0x" + "00" * 20


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, url, timeout=60, retries=3):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.calls = 0
        self._id = 0

    def call(self, method, params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        last = None
        for attempt in range(self.retries):
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as exc:
                # Some nodes send a JSON-RPC error with a 4xx status; surface its message.
                try:
                    payload = json.loads(exc.read().decode())
                except (ValueError, OSError):
                    payload = None
                if isinstance(payload, dict) and payload.get("error") and exc.code not in (429, 502, 503, 504):
                    break
                last = exc
                time.sleep(0.5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RpcError("%s failed: %s" % (method, last))
        if "error" in payload and payload["error"]:
            raise RpcError("%s: %s" % (method, payload["error"].get("message", payload["error"])))
        return payload.get("result")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def norm_addr(a):
    return "0x" + a.lower().replace("0x", "").rjust(40, "0")[-40:]


def word_to_addr(word):
    return "0x" + word.replace("0x", "").rjust(64, "0")[-40:]


def to_int(h):
    return int(h, 16)


def code_kind(code):
    """Classify eth_getCode output."""
    if not code or code == "0x":
        return "eoa"
    if code.lower().startswith("0xef0100"):
        return "eoa-7702"
    return "contract"


_RANGE_WORDS = ("range", "limit", "too many", "exceed", "block", "archive", "pruned", "result", "timeout", "large")


def looks_like_range_error(message):
    """True when an eth_getLogs error is probably about the block range or result size."""
    msg = message.lower()
    return any(w in msg for w in _RANGE_WORDS)


def fetch_logs(rpc, address, topics, from_block, to_block, chunk=None, max_requests=400):
    """Fetch logs, splitting the range when the node rejects it."""
    logs = []
    work = []
    if chunk:
        start = from_block
        while start <= to_block:
            end = min(start + chunk - 1, to_block)
            work.append((start, end))
            start = end + 1
        work.reverse()
    else:
        work.append((from_block, to_block))
    requests = 0
    while work:
        lo, hi = work.pop()
        if requests >= max_requests:
            raise RpcError("eth_getLogs needed more than %d requests; narrow --from-block or use --chunk" % max_requests)
        requests += 1
        try:
            part = rpc.call("eth_getLogs", [{
                "address": address, "fromBlock": hex(lo), "toBlock": hex(hi), "topics": [topics],
            }])
        except RpcError as exc:
            if lo == hi or not looks_like_range_error(str(exc)):
                raise
            mid = (lo + hi) // 2
            work.append((mid + 1, hi))
            work.append((lo, mid))
            continue
        logs.extend(part)
    return logs, requests


# ---------------------------------------------------------------------------
# Core logic (pure functions, testable without network)
# ---------------------------------------------------------------------------

def parse_events(logs):
    """Turn raw logs into a sorted list of change events."""
    events = []
    for lg in logs:
        if lg.get("removed"):
            continue
        t0 = lg["topics"][0].lower()
        kind = TOPICS.get(t0)
        if kind is None:
            continue
        data = lg.get("data", "0x").replace("0x", "")
        ev = {
            "kind": kind,
            "block": to_int(lg["blockNumber"]),
            "log_index": to_int(lg.get("logIndex", "0x0")),
            "tx": lg.get("transactionHash"),
            "old": None,
            "new": None,
        }
        if kind == "admin":
            if len(lg["topics"]) >= 3:  # some proxies index both arguments
                ev["old"] = word_to_addr(lg["topics"][1])
                ev["new"] = word_to_addr(lg["topics"][2])
            else:
                ev["old"] = word_to_addr(data[0:64])
                ev["new"] = word_to_addr(data[64:128])
        else:
            if len(lg["topics"]) >= 2:
                ev["new"] = word_to_addr(lg["topics"][1])
            else:
                ev["new"] = word_to_addr(data[0:64])
        if "blockTimestamp" in lg:
            ev["timestamp"] = to_int(lg["blockTimestamp"])
        events.append(ev)
    events.sort(key=lambda e: (e["block"], e["log_index"]))
    return events


def replay(events):
    """Fill in 'old' for implementation/beacon events and return last value per kind."""
    last = {"implementation": None, "admin": None, "beacon": None}
    seen_impl = []
    for ev in events:
        k = ev["kind"]
        if k != "admin":
            ev["old"] = last[k]
        if k == "implementation":
            ev["reused"] = ev["new"] in seen_impl
            seen_impl.append(ev["new"])
        last[k] = ev["new"]
    return last


def detect_scheme(slots):
    """Pick which slot family the proxy uses based on non-zero slots."""
    nz = {k for k, v in slots.items() if v and v != ZERO}
    if nz & {"eip1967.implementation", "eip1967.beacon"}:
        return "eip1967"
    if "zos.implementation" in nz:
        return "zeppelinos-legacy"
    if "eip1967.admin" in nz or "zos.admin" in nz:
        return "eip1967" if "eip1967.admin" in nz else "zeppelinos-legacy"
    return "unknown"


def current_state(slots, scheme):
    if scheme == "zeppelinos-legacy":
        impl, admin = slots.get("zos.implementation"), slots.get("zos.admin")
    else:
        impl, admin = slots.get("eip1967.implementation"), slots.get("eip1967.admin")
    beacon = slots.get("eip1967.beacon")
    return {
        "implementation": impl if impl and impl != ZERO else None,
        "admin": admin if admin and admin != ZERO else None,
        "beacon": beacon if beacon and beacon != ZERO else None,
    }


def evaluate(events, last_from_logs, state, codes, beacon_impl=None, scan_from=0):
    """Compare log history with live state and produce findings.

    codes: dict address -> 'contract' | 'eoa' | 'eoa-7702'
    scan_from: first scanned block; a partial scan softens the "no event" wording.
    """
    findings = []

    def why(event_name):
        if scan_from > 0:
            return "has no %s event since block %d (scan did not start at genesis)" % (event_name, scan_from)
        article = "an" if event_name[0] in "AEIOU" else "a"
        return "was never announced by %s %s event (set at deployment or by a direct storage write)" % (article, event_name)

    def add(level, code, msg):
        findings.append({"level": level, "code": code, "message": msg})

    impl = state["implementation"]
    admin = state["admin"]
    beacon = state["beacon"]

    if impl is None and beacon is None:
        add("WARN", "NO_IMPLEMENTATION", "neither an implementation nor a beacon slot is set; this may not be an EIP-1967 / ZeppelinOS proxy")

    # implementation slot vs logs
    if impl is not None:
        if last_from_logs["implementation"] is None:
            add("INFO", "IMPL_WITHOUT_EVENT", "implementation %s %s" % (impl, why("Upgraded")))
        elif last_from_logs["implementation"] != impl:
            add("WARN", "SILENT_IMPLEMENTATION_CHANGE", "implementation slot holds %s but the last Upgraded event says %s" % (impl, last_from_logs["implementation"]))
        else:
            add("OK", "IMPL_MATCHES_LOGS", "implementation slot matches the last Upgraded event (%s)" % impl)
        if codes.get(impl) != "contract":
            add("WARN", "IMPL_NO_CODE", "implementation %s has no code; every call through the proxy will fail or silently succeed" % impl)
    # admin slot vs logs
    if admin is not None:
        if last_from_logs["admin"] is None:
            add("INFO", "ADMIN_WITHOUT_EVENT", "admin %s %s" % (admin, why("AdminChanged")))
        elif last_from_logs["admin"] != admin:
            add("WARN", "SILENT_ADMIN_CHANGE", "admin slot holds %s but the last AdminChanged event says %s" % (admin, last_from_logs["admin"]))
        else:
            add("OK", "ADMIN_MATCHES_LOGS", "admin slot matches the last AdminChanged event (%s)" % admin)
        kind = codes.get(admin)
        if kind in ("eoa", "eoa-7702"):
            add("WARN", "ADMIN_IS_EOA", "admin %s is an externally owned account (%s); a single key can upgrade this proxy" % (admin, kind))
    elif beacon is None and events:
        add("INFO", "ADMIN_SLOT_EMPTY", "admin slot is empty; upgrades (if any) are controlled by the implementation (UUPS) or the proxy has been frozen")
    # beacon
    if beacon is not None:
        if last_from_logs["beacon"] is None:
            add("INFO", "BEACON_WITHOUT_EVENT", "beacon %s %s" % (beacon, why("BeaconUpgraded")))
        elif last_from_logs["beacon"] != beacon:
            add("WARN", "SILENT_BEACON_CHANGE", "beacon slot holds %s but the last BeaconUpgraded event says %s" % (beacon, last_from_logs["beacon"]))
        else:
            add("OK", "BEACON_MATCHES_LOGS", "beacon slot matches the last BeaconUpgraded event (%s)" % beacon)
        if codes.get(beacon) != "contract":
            add("WARN", "BEACON_NO_CODE", "beacon %s has no code" % beacon)
        elif beacon_impl is None:
            add("WARN", "BEACON_IMPL_UNREADABLE", "beacon %s did not answer implementation()" % beacon)
        elif codes.get(beacon_impl) != "contract":
            add("WARN", "BEACON_IMPL_NO_CODE", "beacon implementation %s has no code" % beacon_impl)

    # history shape
    impl_events = [e for e in events if e["kind"] == "implementation"]
    if impl_events and impl_events[0]["old"] is None:
        add("INFO", "INITIAL_IMPL_UNLOGGED", "the implementation in place before block %d is not in the scanned logs (%s)" % (impl_events[0]["block"], "scan started at block %d" % scan_from if scan_from > 0 else "set at deployment without an event"))
    for ev in events:
        if ev["kind"] == "implementation" and ev.get("reused"):
            add("INFO", "IMPL_REUSED", "block %d: implementation switched back to a previously used address %s" % (ev["block"], ev["new"]))
        if ev["kind"] == "implementation" and codes.get(ev["new"]) not in (None, "contract"):
            add("WARN", "HISTORIC_IMPL_NO_CODE", "block %d: implementation %s has no code today (selfdestructed or never deployed)" % (ev["block"], ev["new"]))
    admins = [e for e in events if e["kind"] == "admin"]
    for i in range(len(admins) - 1):
        a, b = admins[i], admins[i + 1]
        if b["new"] == a["old"] and b["block"] - a["block"] <= 50:
            add("INFO", "ADMIN_ROUND_TRIP", "blocks %d..%d: admin handed to %s and returned to %s (typical temporary upgrader)" % (a["block"], b["block"], a["new"], b["new"]))
    impl_blocks = {}
    for e in events:
        if e["kind"] == "implementation":
            impl_blocks.setdefault(e["block"], []).append(e)
    for blk, evs in impl_blocks.items():
        if len(evs) > 1:
            add("INFO", "MULTI_UPGRADE_SAME_BLOCK", "block %d: %d Upgraded events in one block (intermediate implementation %s)" % (blk, len(evs), evs[0]["new"]))
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(rpc, proxy, from_block=0, to_block=None, chunk=None, with_time=True):
    proxy = norm_addr(proxy)
    chain_id = to_int(rpc.call("eth_chainId", []))
    head = to_int(rpc.call("eth_blockNumber", []))
    if to_block is None:
        to_block = head
    slots = {name: word_to_addr(rpc.call("eth_getStorageAt", [proxy, slot, "latest"]))
             for name, slot in SLOTS.items()}
    scheme = detect_scheme(slots)
    state = current_state(slots, scheme)

    logs, requests = fetch_logs(rpc, proxy, list(TOPICS.keys()), from_block, to_block, chunk=chunk)
    events = parse_events(logs)
    last = replay(events)

    beacon_impl = None
    if state["beacon"]:
        try:
            res = rpc.call("eth_call", [{"to": state["beacon"], "data": SEL_IMPLEMENTATION}, "latest"])
            if res and len(res) >= 66:
                beacon_impl = word_to_addr(res[:66])
        except RpcError:
            beacon_impl = None

    addrs = set(v for v in state.values() if v)
    if beacon_impl:
        addrs.add(beacon_impl)
    for ev in events:
        for k in ("old", "new"):
            if ev[k] and ev[k] != ZERO:
                addrs.add(ev[k])
    codes = {a: code_kind(rpc.call("eth_getCode", [a, "latest"])) for a in sorted(addrs)}

    if with_time:
        cache = {}
        for ev in events:
            if "timestamp" in ev:
                continue
            if ev["block"] not in cache:
                blk = rpc.call("eth_getBlockByNumber", [hex(ev["block"]), False])
                cache[ev["block"]] = to_int(blk["timestamp"]) if blk else None
            ev["timestamp"] = cache[ev["block"]]

    findings = evaluate(events, last, state, codes, beacon_impl, scan_from=from_block)
    return {
        "proxy": proxy,
        "chain_id": chain_id,
        "scheme": scheme,
        "slots": slots,
        "state": state,
        "beacon_implementation": beacon_impl,
        "codes": codes,
        "scan": {"from_block": from_block, "to_block": to_block, "events": len(events), "log_requests": requests},
        "events": events,
        "last_from_logs": last,
        "findings": findings,
    }


def fmt_time(ts):
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def render(result):
    out = []
    st = result["state"]
    codes = result["codes"]

    def tag(a):
        if a is None:
            return "none"
        return "%s (%s)" % (a, codes.get(a, "?"))

    out.append("proxy: %s  chain id: %d  scheme: %s" % (result["proxy"], result["chain_id"], result["scheme"]))
    out.append("implementation: %s" % tag(st["implementation"]))
    out.append("admin:          %s" % tag(st["admin"]))
    out.append("beacon:         %s" % tag(st["beacon"]))
    if result["beacon_implementation"]:
        out.append("beacon impl:    %s" % tag(result["beacon_implementation"]))
    sc = result["scan"]
    out.append("logs: blocks %d..%d, %d events, %d eth_getLogs request(s)" % (sc["from_block"], sc["to_block"], sc["events"], sc["log_requests"]))
    out.append("")
    out.append("timeline:")
    if not result["events"]:
        out.append("  (no Upgraded / AdminChanged / BeaconUpgraded events in range)")
    for i, ev in enumerate(result["events"], 1):
        old = ev["old"] or "(unknown)"
        out.append("  %2d. block %-10d %s  %-14s %s -> %s" % (
            i, ev["block"], fmt_time(ev.get("timestamp")), ev["kind"], old, ev["new"]))
        out.append("      tx %s" % ev["tx"])
    out.append("")
    out.append("checks:")
    for f in result["findings"]:
        out.append("  %-4s %-28s %s" % (f["level"], f["code"], f["message"]))
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Rebuild an upgradeable proxy's admin/implementation/beacon history from logs and check it against live storage.")
    p.add_argument("--rpc", required=True, help="JSON-RPC endpoint URL")
    p.add_argument("--proxy", required=True, help="proxy contract address")
    p.add_argument("--from-block", type=int, default=0, help="first block to scan (default 0)")
    p.add_argument("--to-block", type=int, default=None, help="last block to scan (default latest)")
    p.add_argument("--chunk", type=int, default=None, help="fixed eth_getLogs block range per request (default: whole range, split on error)")
    p.add_argument("--no-time", action="store_true", help="skip block timestamp lookups")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = p.parse_args(argv)

    rpc = Rpc(args.rpc)
    try:
        result = run(rpc, args.proxy, args.from_block, args.to_block, args.chunk, not args.no_time)
    except RpcError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
    return 1 if any(f["level"] == "WARN" for f in result["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
