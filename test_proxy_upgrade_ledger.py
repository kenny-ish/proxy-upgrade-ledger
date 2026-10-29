import hashlib
import unittest

import proxy_upgrade_ledger as m

ZOS_IMPL_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"
ZOS_ADMIN_SLOT = "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b"
EIP_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

T_UP = "0xbc7cd75a20ee27fd9adebab32041f755214dbc6bffa90cc0225b39da2e5c2d3b"
T_ADM = "0x7e644d79422f17c01e4894b5f4f588d331ebfa28653d42ae832dc59e38c9798f"
T_BEA = "0x1cf3b03a6cf19fa2baba4df148e9dcabedea7f8a5c07840e207e5c089be95d3e"

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
CIRCLE_ADMIN = "0x807a96288a1a408dbc13de2b1d087d10356395d2"
USDC_V2 = "0xb7277a6e95992041568d9391d09d0122023778a2"
USDC_V21 = "0xa2327a938febf5fec13bacfb16ae10ecbc4cbdcf"
USDC_V22 = "0x43506849d7c04f9138d1a2050bbf3a0c054402dd"
TMP_2020 = "0xed24bd79a3f2ba4325e9c553164e299c65e272fc"
TMP_2024 = "0x9999fa87f5a1d1c64e7c709838b92006ab0cc1ad"


def w(addr):
    return "0x" + addr[2:].rjust(64, "0")


def log(block, idx, topics, data="0x", tx="0xtx"):
    return {"blockNumber": hex(block), "logIndex": hex(idx), "topics": topics,
            "data": data, "transactionHash": tx, "removed": False}


# Ethereum mainnet, USDC proxy (ZeppelinOS AdminUpgradeabilityProxy).
# Subset of the real AdminChanged / Upgraded logs, as returned by eth_getLogs.
USDC_LOGS = [
    log(10743406, 0, [T_ADM], "0x" + w(CIRCLE_ADMIN)[2:] + w(TMP_2020)[2:],
        "0x621f3c01567c619197df60b25e083f393d22b9a6c7718b45a279d8ab77d8620d"),
    log(10743414, 1, [T_ADM], "0x" + w(TMP_2020)[2:] + w(CIRCLE_ADMIN)[2:],
        "0xe6f0f754398d89583da8e4229c5d7aaa00739a3ae334ecfc2839ac396b4836e3"),
    log(10743414, 0, [T_UP], w(USDC_V2),
        "0xe6f0f754398d89583da8e4229c5d7aaa00739a3ae334ecfc2839ac396b4836e3"),
    log(12317814, 0x56, [T_UP], w(USDC_V21),
        "0xe2e40640ffd5f76538cd23660cf56f00bfebd5fe925ebad6b8067c4cee18a2c3"),
    log(18963710, 0x2a, [T_ADM], "0x" + w(CIRCLE_ADMIN)[2:] + w(TMP_2024)[2:],
        "0x4441f5f0d30b59f9db3083034605e5cfb35e3606a30e12f075feef3b1df81a15"),
    log(18963716, 0x146, [T_UP], w(USDC_V22),
        "0xae3ad89e569f27d47a8a02999a6d937c12aaa6bc50e66650e7cbd3244bde9951"),
    log(18963716, 0x147, [T_ADM], "0x" + w(TMP_2024)[2:] + w(CIRCLE_ADMIN)[2:],
        "0xae3ad89e569f27d47a8a02999a6d937c12aaa6bc50e66650e7cbd3244bde9951"),
]
# eth_getStorageAt(USDC, slot, "latest") observed on mainnet at block 26166034
USDC_SLOTS = {
    ZOS_IMPL_SLOT: w(USDC_V22),
    ZOS_ADMIN_SLOT: w(CIRCLE_ADMIN),
}

# OP Mainnet, L2StandardBridge predeploy 0x4200...0010 (EIP-1967, indexed topics).
OP_PROXY = "0x4200000000000000000000000000000000000010"
OP_ADMIN = "0x4200000000000000000000000000000000000018"
OP_TMP = "0x2a5a3eabb9fd571a3af0299eebdf8eaafe29a914"
OP_IMPL = "0xae9ed42f43a3ee45c3a9def8ae6b48cbb58ed1a1"
OP_TX = "0xd2e9eb2ba77098610e7dda134e70f741f7456f4ec49912d667860c40988dfd8e"
OP_LOGS = [
    dict(log(0x92d4d24, 0x2b, [T_UP, w(OP_TMP)], "0x", OP_TX), blockTimestamp="0x6a4e7401"),
    dict(log(0x92d4d24, 0x2c, [T_UP, w(OP_IMPL)], "0x", OP_TX), blockTimestamp="0x6a4e7401"),
]
OP_SLOTS = {EIP_IMPL_SLOT: w(OP_IMPL), EIP_ADMIN_SLOT: w(OP_ADMIN)}


class FakeRpc:
    """Answers JSON-RPC from fixed data. Rejects log ranges wider than max_range."""

    def __init__(self, chain_id, head, logs, slots, codes, max_range=None):
        self.chain_id, self.head, self.logs, self.slots, self.codes = chain_id, head, logs, slots, codes
        self.max_range = max_range
        self.calls = []

    def call(self, method, params):
        self.calls.append(method)
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getStorageAt":
            return self.slots.get(params[1], "0x" + "00" * 32)
        if method == "eth_getCode":
            return self.codes.get(params[0], "0x")
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(1700000000)}
        if method == "eth_getLogs":
            f = params[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if self.max_range and hi - lo + 1 > self.max_range:
                raise m.RpcError("range too large")
            return [l for l in self.logs if lo <= int(l["blockNumber"], 16) <= hi
                    and l["topics"][0] in f["topics"][0]]
        if method == "eth_call":
            return w(OP_IMPL)
        raise AssertionError(method)


class KeccakTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(m.keccak_hex(b""), "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")

    def test_event_topics(self):
        self.assertEqual(m.TOPIC_UPGRADED, T_UP)
        self.assertEqual(m.TOPIC_ADMIN_CHANGED, T_ADM)
        self.assertEqual(m.TOPIC_BEACON_UPGRADED, T_BEA)
        self.assertEqual(m.SEL_IMPLEMENTATION, "0x5c60da1b")

    def test_slots(self):
        self.assertEqual(m.SLOTS["eip1967.implementation"], EIP_IMPL_SLOT)
        self.assertEqual(m.SLOTS["eip1967.admin"], EIP_ADMIN_SLOT)
        self.assertEqual(m.SLOTS["eip1967.beacon"], EIP_BEACON_SLOT)
        self.assertEqual(m.SLOTS["zos.implementation"], ZOS_IMPL_SLOT)
        self.assertEqual(m.SLOTS["zos.admin"], ZOS_ADMIN_SLOT)

    def test_permutation_against_sha3(self):
        # Same permutation, different padding byte: multi-block absorption must match hashlib.
        for n in (0, 1, 135, 136, 137, 271, 272, 500):
            data = (bytes(range(256)) * 2)[:n]
            self.assertEqual(m._sponge256(data, 0x06), hashlib.sha3_256(data).digest(), n)

    def test_constants_are_complete(self):
        self.assertEqual(len(m._RC), 24)
        self.assertEqual(m._RC[0], 1)
        self.assertEqual(m._RC[23], 0x8000000080008008)
        self.assertEqual(sorted(m._ROT), sorted([0] + [((t + 1) * (t + 2) // 2) % 64 for t in range(24)]))


class ParseTests(unittest.TestCase):
    def test_usdc_timeline(self):
        events = m.parse_events(USDC_LOGS)
        self.assertEqual([e["block"] for e in events],
                         [10743406, 10743414, 10743414, 12317814, 18963710, 18963716, 18963716])
        self.assertEqual(events[1]["kind"], "implementation")  # log index 0 before index 1
        self.assertEqual(events[2]["kind"], "admin")
        last = m.replay(events)
        self.assertEqual(last["implementation"], USDC_V22)
        self.assertEqual(last["admin"], CIRCLE_ADMIN)
        self.assertEqual(events[3]["old"], USDC_V2)
        self.assertFalse(events[3]["reused"])
        # the live slot value agrees with the log history
        self.assertEqual(m.word_to_addr(USDC_SLOTS[ZOS_IMPL_SLOT]), last["implementation"])
        self.assertEqual(m.word_to_addr(USDC_SLOTS[ZOS_ADMIN_SLOT]), last["admin"])

    def test_indexed_topics_and_timestamp(self):
        events = m.parse_events(OP_LOGS)
        self.assertEqual(events[0]["new"], OP_TMP)
        self.assertEqual(events[1]["new"], OP_IMPL)
        self.assertEqual(events[0]["timestamp"], 1783526401)
        self.assertEqual(m.fmt_time(events[0]["timestamp"]), "2026-07-08 16:00:01")

    def test_scheme(self):
        slots = {k: m.word_to_addr(USDC_SLOTS.get(v, "0x0")) for k, v in m.SLOTS.items()}
        self.assertEqual(m.detect_scheme(slots), "zeppelinos-legacy")
        slots = {k: m.word_to_addr(OP_SLOTS.get(v, "0x0")) for k, v in m.SLOTS.items()}
        self.assertEqual(m.detect_scheme(slots), "eip1967")
        self.assertEqual(m.detect_scheme({k: m.ZERO for k in m.SLOTS}), "unknown")

    def test_code_kind(self):
        self.assertEqual(m.code_kind("0x"), "eoa")
        self.assertEqual(m.code_kind("0xef0100" + "11" * 20), "eoa-7702")
        self.assertEqual(m.code_kind("0x6080"), "contract")


class EvaluateTests(unittest.TestCase):
    def codes_of(self, result):
        return {f["code"] for f in result["findings"]}

    def test_usdc_run(self):
        codes = {USDC_V2: "0x60", USDC_V21: "0x60", USDC_V22: "0x60", TMP_2020: "0x60", TMP_2024: "0x60"}
        rpc = FakeRpc(1, 26166034, USDC_LOGS, USDC_SLOTS, codes)
        res = m.run(rpc, USDC, with_time=False)
        self.assertEqual(res["scheme"], "zeppelinos-legacy")
        self.assertEqual(res["state"]["implementation"], USDC_V22)
        self.assertEqual(res["codes"][CIRCLE_ADMIN], "eoa")
        found = self.codes_of(res)
        self.assertIn("IMPL_MATCHES_LOGS", found)
        self.assertIn("ADMIN_MATCHES_LOGS", found)
        self.assertIn("ADMIN_IS_EOA", found)
        self.assertIn("ADMIN_ROUND_TRIP", found)
        self.assertIn("INITIAL_IMPL_UNLOGGED", found)
        self.assertNotIn("SILENT_IMPLEMENTATION_CHANGE", found)
        self.assertEqual(sum(1 for f in res["findings"] if f["code"] == "ADMIN_ROUND_TRIP"), 2)
        text = m.render(res)
        self.assertIn("scheme: zeppelinos-legacy", text)
        self.assertIn(USDC_V22, text)

    def test_op_run(self):
        codes = {OP_IMPL: "0x60", OP_ADMIN: "0x60", OP_TMP: "0x60"}
        rpc = FakeRpc(10, 158042380, OP_LOGS, OP_SLOTS, codes)
        res = m.run(rpc, OP_PROXY)
        found = self.codes_of(res)
        self.assertEqual(res["scheme"], "eip1967")
        self.assertIn("MULTI_UPGRADE_SAME_BLOCK", found)
        self.assertIn("ADMIN_WITHOUT_EVENT", found)
        self.assertIn("IMPL_MATCHES_LOGS", found)
        self.assertNotIn("ADMIN_IS_EOA", found)
        self.assertNotIn("eth_getBlockByNumber", rpc.calls)  # timestamps came with the logs

    def test_silent_change_and_no_code(self):
        slots = {EIP_IMPL_SLOT: w(OP_TMP), EIP_ADMIN_SLOT: w(OP_ADMIN)}
        rpc = FakeRpc(10, 158042380, OP_LOGS, slots, {OP_ADMIN: "0x60"})
        res = m.run(rpc, OP_PROXY, with_time=False)
        found = self.codes_of(res)
        self.assertIn("SILENT_IMPLEMENTATION_CHANGE", found)
        self.assertIn("IMPL_NO_CODE", found)
        self.assertIn("HISTORIC_IMPL_NO_CODE", found)

    def test_beacon(self):
        beacon = "0x" + "bb" * 20
        slots = {EIP_BEACON_SLOT: w(beacon)}
        logs = [log(100, 0, [T_BEA, w(beacon)])]
        rpc = FakeRpc(1, 200, logs, slots, {beacon: "0x60", OP_IMPL: "0x60"})
        res = m.run(rpc, "0x" + "cc" * 20, with_time=False)
        self.assertEqual(res["beacon_implementation"], OP_IMPL)
        found = self.codes_of(res)
        self.assertIn("BEACON_MATCHES_LOGS", found)
        self.assertNotIn("NO_IMPLEMENTATION", found)

    def test_log_range_splitting(self):
        rpc = FakeRpc(1, 26166034, USDC_LOGS, USDC_SLOTS, {}, max_range=3_000_000)
        logs, requests = m.fetch_logs(rpc, USDC, [T_UP, T_ADM], 0, 26166034)
        self.assertEqual(len(logs), len(USDC_LOGS))
        self.assertGreater(requests, 8)
        with self.assertRaises(m.RpcError):
            m.fetch_logs(rpc, USDC, [T_UP], 0, 26166034, max_requests=3)
        logs, requests = m.fetch_logs(rpc, USDC, [T_UP], 10_000_000, 19_999_999, chunk=2_500_000)
        self.assertEqual(requests, 4)
        self.assertEqual(len(logs), 3)


if __name__ == "__main__":
    unittest.main()
