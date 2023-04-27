# Copyright The Lightning AI team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import sys
import time

import pytest

from lightning.fabric.accelerators.xla import _XLA_AVAILABLE, XLAAccelerator
from tests_fabric.helpers.runif import RunIf


@pytest.mark.skipif(_XLA_AVAILABLE, reason="test requires torch_xla to be absent")
def test_tpu_device_absence():
    """Check `is_available` returns True when TPU is available."""
    assert not XLAAccelerator.is_available()


@RunIf(tpu=True)
def test_tpu_device_presence():
    """Check `is_available` returns True when TPU is available."""
    assert XLAAccelerator.is_available()


def _t1_5():
    time.sleep(1.5)
    return True


# this test runs very slowly on these platforms
@RunIf(skip_windows=True)
@pytest.mark.skipif(sys.platform == "darwin", reason="Times out")
def test_result_returns_within_timeout_seconds(monkeypatch):
    """Check that the TPU availability process launch returns within 3 seconds."""
    from lightning.fabric.accelerators import xla

    timeout = 3
    monkeypatch.setattr(xla, "_XLA_AVAILABLE", True)
    monkeypatch.setattr(xla, "TPU_CHECK_TIMEOUT", timeout)
    monkeypatch.setattr(xla, "_has_tpu_device", _t1_5)
    xla.XLAAccelerator.is_available.cache_clear()

    start = time.monotonic()

    result = xla.XLAAccelerator.is_available()

    end = time.monotonic()
    elapsed_time = end - start

    # around 1.5 but definitely not 3 (timeout time)
    assert 1 < elapsed_time < 2, elapsed_time
    assert result

    xla.XLAAccelerator.is_available.cache_clear()


def _t3():
    time.sleep(3)
    return True


def test_timeout_triggered(monkeypatch):
    """Check that the TPU availability process launch returns within 3 seconds."""
    from lightning.fabric.accelerators import xla

    timeout = 1.5
    monkeypatch.setattr(xla, "_XLA_AVAILABLE", True)
    monkeypatch.setattr(xla, "TPU_CHECK_TIMEOUT", timeout)
    monkeypatch.setattr(xla, "_has_tpu_device", _t3)
    xla.XLAAccelerator.is_available.cache_clear()

    start = time.monotonic()

    with pytest.raises(TimeoutError, match="Timed out waiting"):
        xla.XLAAccelerator.is_available()

    end = time.monotonic()
    elapsed_time = end - start

    # around 1.5 but definitely not 3 (fn time)
    assert 1 < elapsed_time < 2, elapsed_time

    xla.XLAAccelerator.is_available.cache_clear()
