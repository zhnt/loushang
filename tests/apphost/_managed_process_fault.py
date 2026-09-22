"""Real process-shell fault fixture; test-only ports and non-clean exit."""

import asyncio
import json
import signal
import sys
import threading

from loushang.apphost.managed import _process as module


class Settled:
    async def run(self):
        return 0

    async def close(self, *, retry_timeout=None):
        pass


def main():
    fault = sys.argv[1]
    original_runner = asyncio.Runner

    class FaultRunner(original_runner):
        def get_loop(self):
            loop = super().get_loop()
            if fault == "init":
                raise RuntimeError("injected setup after native loop creation")
            return loop

        def close(self):
            super().close()
            if fault == "close":
                raise RuntimeError("injected partial close")

    module.asyncio.Runner = FaultRunner
    original_signal = signal.signal
    failed_install = False

    def setter(kind, value):
        nonlocal failed_install
        result = original_signal(kind, value)
        if fault == "install" and kind == signal.SIGTERM and not failed_install:
            failed_install = True
            raise RuntimeError("injected installation after native effect")
        return result

    module.signal.signal = setter
    process = module._ChildProcess(Settled(), Settled())
    finished = threading.Event()
    companion = threading.Thread(target=finished.wait)
    companion.start()  # Real unmasked concurrent thread, including after return.

    def receipt():
        return {"unknown": process.unknown, "pending": process.cleanup_pending,
                "stopRequested": process._stop_requested,
                "protected": signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
                and all(signal.getsignal(kind) == process._signal for kind in (signal.SIGINT, signal.SIGTERM))}

    def observe():
        print(json.dumps(receipt()), flush=True)
        for command in sys.stdin:
            if command.strip() == "quit":
                # Deliberate test-only termination, not a production receipt.
                raise SystemExit(9 if fault == "success" else 7)
            assert command.strip() == "status"
            print(json.dumps(receipt()), flush=True)
        raise SystemExit(8)

    module._park = observe
    try:
        result = process.run()
        assert fault == "success" and result == 0
        observe()  # Final test diagnostics; never start another application.
    finally:
        finished.set()
        companion.join(2)
        assert not companion.is_alive()


if __name__ == "__main__":
    main()
