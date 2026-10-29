# proxy-upgrade-ledger

Rebuilds the full admin / implementation / beacon history of an upgradeable proxy from its
`Upgraded`, `AdminChanged` and `BeaconUpgraded` logs, then checks that history against the
live EIP-1967 (or legacy ZeppelinOS) storage slots. It tells you who could upgrade the
contract, every implementation it has ever pointed at, and whether anything in storage
changed without an event. It talks to a JSON-RPC node only and uses the Python standard
library only.

## Example

USDC on Ethereum mainnet (ZeppelinOS-era proxy, admin is a plain EOA):

```
$ python proxy_upgrade_ledger.py --rpc https://mainnet.gateway.tenderly.co --proxy 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
proxy: 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48  chain id: 1  scheme: zeppelinos-legacy
implementation: 0x43506849d7c04f9138d1a2050bbf3a0c054402dd (contract)
admin:          0x807a96288a1a408dbc13de2b1d087d10356395d2 (eoa)
beacon:         none
logs: blocks 0..26166115, 11 events, 1 eth_getLogs request(s)

timeline:
   1. block 6082473    2018-08-03 19:30:30  admin          0x95ba4cf87d6723ad9c0db21737d862be80e93911 -> 0x69005ff70072c57547dc44ea975d85ea60e5b196
      tx 0xf73f2dd1e79552c5e13e92b16ed0a3a59b9e28fd134d6759a4e8cfbf3385a3c6
   2. block 6278324    2018-09-05 20:42:05  admin          0x69005ff70072c57547dc44ea975d85ea60e5b196 -> 0x807a96288a1a408dbc13de2b1d087d10356395d2
      tx 0xda436c8e42f88e4c9478b03ff525dfba7035be7d894bf91ca5321bf3c360f7d9
   3. block 10743406   2020-08-27 15:31:35  admin          0x807a96288a1a408dbc13de2b1d087d10356395d2 -> 0xed24bd79a3f2ba4325e9c553164e299c65e272fc
      tx 0x621f3c01567c619197df60b25e083f393d22b9a6c7718b45a279d8ab77d8620d
   4. block 10743414   2020-08-27 15:32:54  implementation (unknown) -> 0xb7277a6e95992041568d9391d09d0122023778a2
      tx 0xe6f0f754398d89583da8e4229c5d7aaa00739a3ae334ecfc2839ac396b4836e3
   5. block 10743414   2020-08-27 15:32:54  admin          0xed24bd79a3f2ba4325e9c553164e299c65e272fc -> 0x807a96288a1a408dbc13de2b1d087d10356395d2
      tx 0xe6f0f754398d89583da8e4229c5d7aaa00739a3ae334ecfc2839ac396b4836e3
   6. block 12317806   2021-04-26 19:13:20  admin          0x807a96288a1a408dbc13de2b1d087d10356395d2 -> 0xd13689e8da0ed95b55100e27b7dbc95c03b5259b
      tx 0x5c5ffdeab45e37fdb2112c5e09a2e361d59faa3eed9e0584fe3ad50de5bfeaca
   7. block 12317814   2021-04-26 19:14:51  implementation 0xb7277a6e95992041568d9391d09d0122023778a2 -> 0xa2327a938febf5fec13bacfb16ae10ecbc4cbdcf
      tx 0xe2e40640ffd5f76538cd23660cf56f00bfebd5fe925ebad6b8067c4cee18a2c3
   8. block 12317814   2021-04-26 19:14:51  admin          0xd13689e8da0ed95b55100e27b7dbc95c03b5259b -> 0x807a96288a1a408dbc13de2b1d087d10356395d2
      tx 0xe2e40640ffd5f76538cd23660cf56f00bfebd5fe925ebad6b8067c4cee18a2c3
   9. block 18963710   2024-01-08 17:15:23  admin          0x807a96288a1a408dbc13de2b1d087d10356395d2 -> 0x9999fa87f5a1d1c64e7c709838b92006ab0cc1ad
      tx 0x4441f5f0d30b59f9db3083034605e5cfb35e3606a30e12f075feef3b1df81a15
  10. block 18963716   2024-01-08 17:16:35  implementation 0xa2327a938febf5fec13bacfb16ae10ecbc4cbdcf -> 0x43506849d7c04f9138d1a2050bbf3a0c054402dd
      tx 0xae3ad89e569f27d47a8a02999a6d937c12aaa6bc50e66650e7cbd3244bde9951
  11. block 18963716   2024-01-08 17:16:35  admin          0x9999fa87f5a1d1c64e7c709838b92006ab0cc1ad -> 0x807a96288a1a408dbc13de2b1d087d10356395d2
      tx 0xae3ad89e569f27d47a8a02999a6d937c12aaa6bc50e66650e7cbd3244bde9951

checks:
  OK   IMPL_MATCHES_LOGS            implementation slot matches the last Upgraded event (0x43506849d7c04f9138d1a2050bbf3a0c054402dd)
  OK   ADMIN_MATCHES_LOGS           admin slot matches the last AdminChanged event (0x807a96288a1a408dbc13de2b1d087d10356395d2)
  WARN ADMIN_IS_EOA                 admin 0x807a96288a1a408dbc13de2b1d087d10356395d2 is an externally owned account (eoa); a single key can upgrade this proxy
  INFO INITIAL_IMPL_UNLOGGED        the implementation in place before block 10743414 is not in the scanned logs (set at deployment without an event)
  INFO ADMIN_ROUND_TRIP             blocks 10743406..10743414: admin handed to 0xed24bd79a3f2ba4325e9c553164e299c65e272fc and returned to 0x807a96288a1a408dbc13de2b1d087d10356395d2 (typical temporary upgrader)
  INFO ADMIN_ROUND_TRIP             blocks 12317806..12317814: admin handed to 0xd13689e8da0ed95b55100e27b7dbc95c03b5259b and returned to 0x807a96288a1a408dbc13de2b1d087d10356395d2 (typical temporary upgrader)
  INFO ADMIN_ROUND_TRIP             blocks 18963710..18963716: admin handed to 0x9999fa87f5a1d1c64e7c709838b92006ab0cc1ad and returned to 0x807a96288a1a408dbc13de2b1d087d10356395d2 (typical temporary upgrader)
```

The L2StandardBridge predeploy on OP Mainnet (EIP-1967, two `Upgraded` events in one
transaction because the upgrade goes through an intermediate StorageSetter contract):

```
$ python proxy_upgrade_ledger.py --rpc https://mainnet.optimism.io --proxy 0x4200000000000000000000000000000000000010
proxy: 0x4200000000000000000000000000000000000010  chain id: 10  scheme: eip1967
implementation: 0xae9ed42f43a3ee45c3a9def8ae6b48cbb58ed1a1 (contract)
admin:          0x4200000000000000000000000000000000000018 (contract)
beacon:         none
logs: blocks 0..158042841, 2 events, 1 eth_getLogs request(s)

timeline:
   1. block 153963812  2026-07-08 16:00:01  implementation (unknown) -> 0x2a5a3eabb9fd571a3af0299eebdf8eaafe29a914
      tx 0xd2e9eb2ba77098610e7dda134e70f741f7456f4ec49912d667860c40988dfd8e
   2. block 153963812  2026-07-08 16:00:01  implementation 0x2a5a3eabb9fd571a3af0299eebdf8eaafe29a914 -> 0xae9ed42f43a3ee45c3a9def8ae6b48cbb58ed1a1
      tx 0xd2e9eb2ba77098610e7dda134e70f741f7456f4ec49912d667860c40988dfd8e

checks:
  OK   IMPL_MATCHES_LOGS            implementation slot matches the last Upgraded event (0xae9ed42f43a3ee45c3a9def8ae6b48cbb58ed1a1)
  INFO ADMIN_WITHOUT_EVENT          admin 0x4200000000000000000000000000000000000018 was never announced by an AdminChanged event (set at deployment or by a direct storage write)
  INFO INITIAL_IMPL_UNLOGGED        the implementation in place before block 153963812 is not in the scanned logs (set at deployment without an event)
  INFO MULTI_UPGRADE_SAME_BLOCK     block 153963812: 2 Upgraded events in one block (intermediate implementation 0x2a5a3eabb9fd571a3af0299eebdf8eaafe29a914)
```

The exit code is 1 when at least one `WARN` finding exists, 0 otherwise, 2 on RPC failure.

## Usage

```
python proxy_upgrade_ledger.py --rpc URL --proxy ADDRESS [options]

  --rpc URL          JSON-RPC endpoint (required)
  --proxy ADDRESS    proxy contract address (required)
  --from-block N     first block to scan (default 0)
  --to-block N       last block to scan (default latest)
  --chunk N          fixed block range per eth_getLogs request
                     (default: ask for the whole range and split in half when the node refuses)
  --no-time          skip block timestamp lookups
  --json             print the full result (slots, events, findings) as JSON
```

Nodes that cap `eth_getLogs` ranges work, but a scan from genesis may need many requests;
the tool stops after 400 and asks you to narrow `--from-block` or set `--chunk`.

## How it works

1. Reads the five well-known slots with `eth_getStorageAt`: EIP-1967 implementation,
   admin and beacon (`keccak256(label) - 1`) and the older ZeppelinOS
   `org.zeppelinos.proxy.implementation` / `.admin` slots. Whichever family is non-zero
   decides the scheme.
2. Pulls every `Upgraded(address)`, `AdminChanged(address,address)` and
   `BeaconUpgraded(address)` log for the proxy, orders them by block and log index, and
   replays them into a timeline. Both indexed and non-indexed argument layouts are handled.
3. Compares the last value seen in the logs with the live slot. A mismatch means the slot
   was written without an event (direct storage write, genesis state, or a non-standard
   proxy) and is reported as `SILENT_*_CHANGE`.
4. Checks `eth_getCode` for every admin and implementation that ever appeared, so an EOA
   admin, a selfdestructed implementation, or an EIP-7702 delegated key shows up.
5. If a beacon is set, calls `implementation()` on it and checks that too.

Event topics and storage slots are computed with a built-in keccak-256 whose round
constants and rotation offsets are generated from the Keccak specification at import time.

## Tests

`python -m unittest -v`
