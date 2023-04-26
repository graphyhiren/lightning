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
from typing import Any

import lightning.fabric as fabric
from lightning.fabric.accelerators import XLAAccelerator
from lightning.fabric.strategies import _StrategyRegistry
from lightning.fabric.strategies.single_xla import SingleDeviceXLAStrategy
from lightning.fabric.utilities.rank_zero import rank_zero_deprecation


def _patch_sys_modules() -> None:
    self = sys.modules[__name__]
    sys.modules["lightning.fabric.strategies.single_tpu"] = self
    sys.modules["lightning.fabric.accelerators.tpu"] = self


class SingleTPUStrategy(SingleDeviceXLAStrategy):
    """Legacy class.

    Use :class:`~lightning.fabric.strategies.single_xla.SingleDeviceXLAStrategy` instead.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        rank_zero_deprecation("The 'single_tpu' strategy is deprecated. Use 'single_xla' instead.")
        super().__init__(*args, **kwargs)

    @classmethod
    def register_strategies(cls, strategy_registry: _StrategyRegistry) -> None:
        strategy_registry.register("single_tpu", cls, description="Legacy class. Use `single_xla` instead.")


class TPUAccelerator(XLAAccelerator):
    """Legacy class.

    Use :class:`~lightning.fabric.accelerators.xla.XLAAccelerator` instead.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        rank_zero_deprecation(
            "The `TPUAccelerator` class is deprecated. Use `lightning.fabric.accelerators.XLAAccelerator` instead."
        )
        super().__init__(*args, **kwargs)


def _patch_classes() -> None:
    setattr(fabric.strategies, "SingleTPUStrategy", SingleTPUStrategy)
    setattr(fabric.accelerators, "TPUAccelerator", TPUAccelerator)


_patch_sys_modules()
_patch_classes()

SingleTPUStrategy.register_strategies(fabric.strategies.STRATEGY_REGISTRY)
