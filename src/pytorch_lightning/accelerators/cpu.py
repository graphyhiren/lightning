# Copyright The PyTorch Lightning team.
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
from typing import Any, Dict, List, Union

import torch

import pytorch_lightning as pl
from pytorch_lightning.accelerators.accelerator import Accelerator
from lightning_lite.lite.utilities.imports import _PSUTIL_AVAILABLE
from lightning_lite.lite.utilities.types import _DEVICE


class CPUAccelerator(Accelerator):
    """Accelerator for CPU devices."""

    def setup(self, trainer: "pl.Trainer") -> None:
        pass

    def setup_environment(self, root_device: torch.device) -> None:
        """
        Raises:
            MisconfigurationException:
                If the selected device is not CPU.
        """
        super().setup_environment(root_device)
        if root_device.type != "cpu":
            raise ValueError(f"Device should be CPU, got {root_device} instead.")

    def get_device_stats(self, device: _DEVICE) -> Dict[str, Any]:
        """Get CPU stats from ``psutil`` package."""
        return get_cpu_stats()

    @staticmethod
    def parse_devices(devices: Union[int, str, List[int]]) -> int:
        """Accelerator device parsing logic."""
        devices = parse_cpu_cores(devices)
        return devices

    @staticmethod
    def get_parallel_devices(devices: Union[int, str, List[int]]) -> List[torch.device]:
        """Gets parallel devices for the Accelerator."""
        devices = parse_cpu_cores(devices)
        return [torch.device("cpu")] * devices

    @staticmethod
    def auto_device_count() -> int:
        """Get the devices when set to auto."""
        return 1

    @staticmethod
    def is_available() -> bool:
        """CPU is always available for execution."""
        return True

    @classmethod
    def register_accelerators(cls, accelerator_registry: Dict) -> None:
        accelerator_registry.register(
            "cpu",
            cls,
            description=f"{cls.__class__.__name__}",
        )


# CPU device metrics
_CPU_VM_PERCENT = "cpu_vm_percent"
_CPU_PERCENT = "cpu_percent"
_CPU_SWAP_PERCENT = "cpu_swap_percent"


def get_cpu_stats() -> Dict[str, float]:
    if not _PSUTIL_AVAILABLE:
        raise ModuleNotFoundError(
            "Fetching CPU device stats requires `psutil` to be installed."
            " Install it by running `pip install -U psutil`."
        )
    import psutil

    return {
        _CPU_VM_PERCENT: psutil.virtual_memory().percent,
        _CPU_PERCENT: psutil.cpu_percent(),
        _CPU_SWAP_PERCENT: psutil.swap_memory().percent,
    }


def parse_cpu_cores(cpu_cores: Union[int, str, List[int]]) -> int:
    """Parses the cpu_cores given in the format as accepted by the ``devices`` argument in the
    :class:`~pytorch_lightning.trainer.Trainer`.

    Args:
        cpu_cores: An int > 0.

    Returns:
        an int representing the number of processes

    Raises:
        MisconfigurationException:
            If cpu_cores is not an int > 0
    """
    if isinstance(cpu_cores, str) and cpu_cores.strip().isdigit():
        cpu_cores = int(cpu_cores)

    if not isinstance(cpu_cores, int) or cpu_cores <= 0:
        raise ValueError("`devices` selected with `CPUAccelerator` should be an int > 0.")

    return cpu_cores
