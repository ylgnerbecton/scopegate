"""Real process signals drain the delivery loop without acquiring handler locks."""

import json
import os
import signal
import subprocess
import sys
from textwrap import dedent

import pytest

PROBE = dedent("""
    import json
    import os
    import signal
    import sys
    import threading
    import time
    from types import SimpleNamespace

    import scopegate.worker as worker

    case, signum = sys.argv[1], int(sys.argv[2])
    calls = []
    condition = threading.Event()
    # The previous worker used this same Event for its signal handler.
    threading.Event = lambda: condition

    def settings():
        calls.append("settings")
        if case == "startup":
            os.kill(os.getpid(), signum)

    def batch(owner, limit):
        calls.append("claim")
        assert limit == 1 and owner.startswith("worker:")
        if case == "locked_cycle":
            with condition._cond:
                os.kill(os.getpid(), signum)
                calls.append("signal_returned")
        assert calls.count("claim") == 1, "Worker claimed again after shutdown"
        return {}

    def sleep(duration):
        assert case == "idle", "Worker slept after receiving shutdown"
        assert 0 < duration <= 0.1
        calls.append("sleep")
        os.kill(os.getpid(), signum)

    worker.get_settings = settings
    worker.telemetry.initialize = lambda: calls.append("initialize")
    worker.telemetry.flush = lambda: calls.append("flush")
    worker.process_batch = batch
    worker.purge = lambda: calls.append("purge")
    worker.get_engine = lambda: SimpleNamespace(dispose=lambda: calls.append("dispose"))
    time.sleep = sleep
    worker.main()
    print(json.dumps(calls))
""")


@pytest.mark.operations
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("case", ["locked_cycle", "startup", "idle"])
def test_real_signal_drains_worker_without_deadlock_or_further_claims(case, signum):
    result = subprocess.run(
        [sys.executable, "-c", PROBE, case, str(signum)],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    expected = {
        "locked_cycle": ["settings", "initialize", "claim", "signal_returned", "purge", "dispose", "flush"],
        "startup": ["settings", "initialize", "dispose", "flush"],
        "idle": ["settings", "initialize", "claim", "purge", "sleep", "dispose", "flush"],
    }
    assert json.loads(result.stdout) == expected[case]
