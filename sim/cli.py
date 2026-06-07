"""CLI for the Tenet mixnet + DHT simulator (multi-site / multi-realization "three modes" harness).

Usage examples:
    uv run python -m sim up sim/scenarios/all-local-docker-small.yaml --netem --wait
    uv run python -m sim demo-payments sim/scenarios/all-local-docker-small.yaml --netem
      (or any of your mixed ssh-docker / 1ec2-2laptop / cloud scenarios)

    The demo-payments command resumes the harness for any topology and layers the
    Algorand hackathon payment rail on top: real testnet custodial ALGO + USDC
    payments from a managed sponsor account, voucher issuance (Privacy Pass style,
    transferable/unlinkable), then the private mixnet is live for vouchered asks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .orchestrator import Orchestrator


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sim", description="Tenet mixnet + DHT simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # up
    p_up = sub.add_parser("up", help="Bring up a scenario (local-docker sites for now)")
    p_up.add_argument("scenario", help="Path to scenario YAML/JSON")
    p_up.add_argument("--netem", action="store_true", help="Apply netem profiles after launch")
    p_up.add_argument("--wait", action="store_true", help="Wait briefly for containers to be ready")
    p_up.add_argument("--rebuild", action="store_true", help="Force rebuild of the node image")
    p_up.add_argument("--realization", choices=["docker", "host"], default=None,
                      help="Force 'docker' (real containers) or 'host' (real python processes on this machine). Default=auto.")

    # status
    sub.add_parser("status", help="Show container status for the active session")

    # logs
    p_logs = sub.add_parser("logs", help="Show logs for a node")
    p_logs.add_argument("node_id")
    p_logs.add_argument("-f", "--follow", action="store_true")
    p_logs.add_argument("--tail", type=int, default=100)

    # netem
    sub.add_parser("netem-apply", help="Re-apply netem inside running containers (after manual tc clear, or to change profiles)")

    # down
    p_down = sub.add_parser("down", help="Stop and remove containers for the active session")
    p_down.add_argument("--clean", action="store_true", help="Also remove named volumes (persisted control stores)")

    # plan (no side effects; shows placement, runners, links, etc.)
    p_plan = sub.add_parser("plan", help="Show what the scenario would do (placement, runners, netem) without launching anything")
    p_plan.add_argument("scenario", help="Path to scenario YAML/JSON")

    # demo-payments: hackathon showcase — brings up any multi-site scenario (the "three modes"),
    # then from a managed custodial testnet account does a real ALGO payment + USDC axfer on
    # Algorand testnet, records the txids in a Privacy Pass-style voucher, and leaves the
    # mixnet topology running so you can immediately do vouchered private asks over it
    # (wallets invisible to end users; pre-pay visible on Lora for judges).
    p_pay = sub.add_parser("demo-payments", help="Hackathon payments rail demo: up a scenario (any mode) + real testnet custodial ALGO + USDC payments + voucher issuance")
    p_pay.add_argument("scenario", help="Path to scenario YAML/JSON (use any of the multi-site ones)")
    p_pay.add_argument("--custodial-mnemonic", help="25-word mnemonic for the managed custodial sponsor account (or set TENET_DEMO_CUSTODIAL_MNEMONIC)")
    p_pay.add_argument("--usdc-asa", type=int, default=10458941, help="Testnet USDC ASA id (default common test asset)")
    p_pay.add_argument("--algo-amount", type=int, default=100_000, help="MicroAlgos for the ALGO leg (default 0.1)")
    p_pay.add_argument("--usdc-amount", type=int, default=100_000, help="USDC base units for the USDC leg (default 0.1 if 6 decimals)")
    p_pay.add_argument("--pool", default="demo-pool~tenet", help="Pool name recorded in the voucher")
    p_pay.add_argument("--voucher-out", default="demo-voucher.json", help="Where to write the email-able voucher")
    p_pay.add_argument("--netem", action="store_true", help="Apply netem (recommended for multi-site realism)")
    p_pay.add_argument("--rebuild", action="store_true", help="Rebuild node image")
    p_pay.add_argument("--realization", choices=["docker", "host"], default=None)

    # (Future) run-workload, chaos, etc. are stubbed for now.

    args = ap.parse_args(argv)
    orch = Orchestrator()

    if args.cmd == "up":
        sess = orch.up(
            args.scenario,
            netem=args.netem,
            wait=args.wait,
            rebuild=args.rebuild,
            realization=getattr(args, "realization", None),
        )
        print("UP complete.")
        st = orch.status(sess)
        print("Nodes:", st)

        # Thick verification for local host runs: exercise the real Kademlia
        # overlays launched in the child processes for nodes placed in different
        # logical sites. We bootstrap short-lived probe overlays to the dht ports
        # of two control_dht nodes (from different sites in the scenario) and
        # confirm a value stored via one peer is retrievable via the other.
        h = getattr(sess, "_host_handle", None)
        if h is not None:
            try:
                import asyncio
                from tenet.mixnet.control import KademliaControlOverlay

                net_id = sess.scenario.network_id
                dht_infos = [(nid, i) for nid, i in h.nodes.items() if i.get("dht_port")]
                if len(dht_infos) >= 2:
                    def site_of(x):
                        return h.nodes.get(x[0], {}).get("site", "")
                    dht_infos.sort(key=lambda x: (site_of(x) != "home", site_of(x)))
                    n1, i1 = dht_infos[0]
                    n2, i2 = dht_infos[-1]
                    p1 = i1["dht_port"]
                    p2 = i2["dht_port"]

                    o1 = KademliaControlOverlay("probe-mesh-1", listen_port=0, network_id=net_id)
                    o1.start(bootstrap=[("127.0.0.1", p1)])
                    o1.wait_for_mesh(2.5)
                    key = f"sim-mesh-{int(time.time())}"
                    val = "from-site-a-to-b"
                    fut = asyncio.run_coroutine_threadsafe(o1.server.set(key, val), o1._loop)
                    fut.result(5)

                    o2 = KademliaControlOverlay("probe-mesh-2", listen_port=0, network_id=net_id)
                    o2.start(bootstrap=[("127.0.0.1", p2)])
                    o2.wait_for_mesh(2.5)
                    fut = asyncio.run_coroutine_threadsafe(o2.server.get(key), o2._loop)
                    got = fut.result(5)
                    o1.stop()
                    o2.stop()
                    ok = (got == val)
                    print("MESH CHECK:", "PASS (value replicated between dht nodes from different logical sites via real Kademlia)" if ok else "got different value")
                else:
                    print("MESH CHECK: only one dht node in scenario; skipping cross-site replication demo")
            except Exception as e:
                print("MESH CHECK: (non-fatal)", e)

        print("Use: python -m sim status | logs <node> | down")
        return 0

    if args.cmd == "status":
        st = orch.status()
        if isinstance(st, dict) and st.get("error") == "no active session":
            # Fallback to persisted session for host runs (so status works after `up` exits)
            p = Path.cwd() / ".tenet-sim-session.json"
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                print("session:", data.get("scenario"))
                print("realization:", data.get("realization"))
                nodes = data.get("nodes", {})
                for nid, info in sorted(nodes.items()):
                    print(f"{nid}: {info}")
                net = data.get("netem", {})
                if net:
                    print("_netem:", net)
                return 0
        for k, v in sorted(st.items()):
            print(f"{k}: {v}")
        return 0

    if args.cmd == "logs":
        # Try in-memory first; if no session, fall back to persisted log path for host.
        p = Path.cwd() / ".tenet-sim-session.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            nodes = data.get("nodes", {})
            info = nodes.get(args.node_id)
            if info and info.get("log"):
                logp = Path(info["log"])
                tailn = args.tail or 100
                if logp.exists():
                    lines = logp.read_text(encoding="utf-8", errors="replace").splitlines()[-tailn:]
                    for line in lines:
                        print(line)
                    if args.follow:
                        print("(follow: tail -f", logp, ")")
                    return 0
        orch.logs(args.node_id, follow=args.follow, tail=args.tail)
        return 0

    if args.cmd == "netem-apply":
        orch.netem_apply()
        print("netem re-applied")
        return 0

    if args.cmd == "down":
        # If we have a persisted host session, handle down directly so it works
        # after the `up` process has exited (real processes, not threads in the cli proc).
        p = Path.cwd() / ".tenet-sim-session.json"
        handled = False
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("realization") == "host":
                import os, time, shutil
                nodes = data.get("nodes", {})
                for nid, info in nodes.items():
                    pid = info.get("pid")
                    if pid:
                        try:
                            os.kill(pid, 15)
                            time.sleep(0.05)
                            os.kill(pid, 9)
                        except Exception:
                            pass
                if args.clean:
                    cd = data.get("cfg_dir")
                    if cd:
                        shutil.rmtree(cd, ignore_errors=True)
                try:
                    p.unlink()
                except Exception:
                    pass
                print("DOWN complete.")
                handled = True
        if not handled:
            orch.down(clean=args.clean)
            print("DOWN complete.")
        return 0

    if args.cmd == "plan":
        plan = orch.plan(args.scenario)
        import json

        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    if args.cmd == "demo-payments":
        import os
        import json as _json
        from pathlib import Path as _Path

        try:
            from algosdk import account, mnemonic
            from tenet.algorand import algod_client, pay_algo, pay_asset, TESTNET_USDC_ASA
            from tenet.vouchers import issue_voucher_batch, save_voucher
        except Exception as e:
            print("demo-payments requires algosdk and the algorand extras. Install with:")
            print("  uv pip install -e '.[algorand]'")
            print("Error:", e)
            return 2

        mn = args.custodial_mnemonic or os.environ.get("TENET_DEMO_CUSTODIAL_MNEMONIC", "").strip()
        if not mn:
            print("Provide --custodial-mnemonic or set TENET_DEMO_CUSTODIAL_MNEMONIC to a funded testnet account (25 words).")
            print("Fund at https://bank.testnet.algorand.network/")
            return 2

        sk = mnemonic.to_private_key(mn)
        addr = account.address_from_private_key(sk)
        print(f"[custodial] sponsor account: {addr}")

        algod = algod_client()

        # 1. Real testnet ALGO payment from the managed custodial account
        # (this is the "visible on-chain pre-pay" for the voucher / x402 flow)
        treasury_sk, treasury = account.generate_account()  # payTo for the pool (receives; no funding needed)
        print(f"[pay-to] {treasury}")
        print(f"[custodial] sending {args.algo_amount/1e6} ALGO ...")
        algo_txid = pay_algo(algod, sk, addr, treasury, args.algo_amount, note=b"tenet-hackathon-demo:algo")
        print(f"[ALGO] confirmed txid={algo_txid}")
        print(f"       https://lora.algokit.io/testnet/tx/{algo_txid}")

        # 2. Real testnet USDC (axfer) from the same custodial account
        # Note: the custodial account must hold the test USDC ASA (or we could opt-in here, but for demo assume pre-funded or use dispenser).
        print(f"[custodial] sending {args.usdc_amount} USDC (asset {args.usdc_asa}) ...")
        try:
            usdc_txid = pay_asset(algod, sk, addr, treasury, args.usdc_asa, args.usdc_amount, note=b"tenet-hackathon-demo:usdc")
            print(f"[USDC] confirmed txid={usdc_txid}")
            print(f"       https://lora.algokit.io/testnet/tx/{usdc_txid}")
        except Exception as e:
            print(f"[USDC] skipped or failed (account may need to opt-in to ASA {args.usdc_asa} first): {e}")
            usdc_txid = None

        # 3. Issue the Privacy Pass-style voucher recording the (primary) pay tx
        # This is the "email the voucher" sponsorship flow — users get N anonymous queries
        # without ever seeing a wallet or seed.
        v = issue_voucher_batch(
            queries=10,
            issuer_secret=os.urandom(32),
            pool=args.pool,
            pay_tx=algo_txid,
        )
        save_voucher(v, args.voucher_out)
        print(f"[voucher] wrote {args.voucher_out} (transferable, unlinkable, {v.queries} queries)")

        # 4. Bring up the requested scenario (this is "resuming the three mode simulation harness").
        # Any of your multi-site scenarios (local-docker only, ssh-docker to EC2/laptop, 1ec2-2laptop, cloud-only, etc.)
        # will work. The payments happened on the real testnet from the managed custodial account;
        # the voucher can now be used for private mixnet queries over the topology.
        print("\n[sim] bringing up scenario (real mixnet + control across the declared sites/modes)...")
        sess = orch.up(
            args.scenario,
            netem=args.netem,
            wait=True,
            rebuild=args.rebuild,
            realization=getattr(args, "realization", None),
        )
        print("[sim] UP complete. Nodes:", orch.status(sess))

        print("\n✅ Hackathon payments + sim showcase complete.")
        print("   - Real ALGO testnet tx from managed custodial (visible on Lora).")
        print("   - Real USDC axfer (if the custodial held the test ASA).")
        print("   - Unlinkable voucher issued for 10 sponsored queries (no user wallet).")
        print(f"   - Mixnet topology live ({args.scenario}). Use the voucher with tenet ask or workloads for private queries.")
        print(f"   Voucher: {args.voucher_out}")
        print("   (Run 'python -m sim status' / logs / down as usual.)")
        return 0

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
