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
"""Test deprecated functionality which will be removed in v1.4.0"""

import pytest
import torch

from pytorch_lightning import Trainer
from pytorch_lightning.overrides.data_parallel import (
    LightningDataParallel,
    LightningDistributedDataParallel,
    LightningParallelModule,
)
from pytorch_lightning.overrides.distributed import LightningDistributedModule
from pytorch_lightning.plugins import DDPSpawnPlugin
from pytorch_lightning.plugins.environments import LightningEnvironment
from tests.deprecated_api import _soft_unimport_module
from tests.helpers import BoringModel
from tests.helpers.runif import RunIf


def test_v1_4_0_deprecated_imports():
    _soft_unimport_module('pytorch_lightning.utilities.argparse_utils')
    with pytest.deprecated_call(match='will be removed in v1.4'):
        from pytorch_lightning.utilities.argparse_utils import _gpus_arg_default  # noqa: F811 F401


class CustomDDPPlugin(DDPSpawnPlugin):

    def configure_ddp(self):
        # old, deprecated implementation
        with pytest.deprecated_call(
            match='`LightningDistributedDataParallel` is deprecated since v1.2 and will be removed in v1.4.'
        ):
            self._model = LightningDistributedDataParallel(
                module=self.lightning_module,
                device_ids=self.determine_ddp_device_ids(),
                **self._ddp_kwargs,
            )
            assert isinstance(self.model, torch.nn.parallel.DistributedDataParallel)
            assert isinstance(self.model.module, LightningDistributedModule)


@RunIf(min_gpus=2, skip_windows=True)
def test_v1_4_0_deprecated_lightning_distributed_data_parallel(tmpdir):
    model = BoringModel()
    trainer = Trainer(
        default_root_dir=tmpdir,
        fast_dev_run=True,
        gpus=2,
        accelerator="ddp_spawn",
        plugins=[
            CustomDDPPlugin(
                parallel_devices=[torch.device("cuda", 0), torch.device("cuda", 1)],
                cluster_environment=LightningEnvironment(),
            )
        ]
    )
    trainer.fit(model)


@RunIf(min_gpus=1)
def test_v1_4_0_deprecated_lightning_data_parallel():
    model = BoringModel()
    with pytest.deprecated_call(match="`LightningDataParallel` is deprecated since v1.2 and will be removed in v1.4."):
        dp_model = LightningDataParallel(model, device_ids=[0])
    assert isinstance(dp_model, torch.nn.DataParallel)
    assert isinstance(dp_model.module, LightningParallelModule)


def test_v1_4_0_deprecated_manual_optimization_optimizer(tmpdir):

    class TestModel(BoringModel):

        def training_step(self, batch, *_, **kwargs):
            opt = self.optimizers()
            output = self.layer(batch)
            loss = self.loss(batch, output)
            self.manual_backward(loss, opt)

        @property
        def automatic_optimization(self):
            return False

    model = TestModel()
    model.training_epoch_end = None
    trainer = Trainer(
        default_root_dir=tmpdir,
        fast_dev_run=True,
    )
    with pytest.deprecated_call(
        match="`optimizer` argument to `manual_backward` is deprecated in v1.2 and will be removed in v1.4"
    ):
        trainer.fit(model)


def test_v1_4_0_deprecated_checkpoint_on(tmpdir):
    from pytorch_lightning.callbacks.model_checkpoint import warning_cache
    warning_cache.clear()

    class TestModel(BoringModel):

        def training_step(self, batch, batch_idx):
            self.log("val_loss", -batch_idx)
            return super().training_step(batch, batch_idx)

    trainer = Trainer(default_root_dir=tmpdir, checkpoint_callback=True, max_epochs=1)

    with pytest.deprecated_call(match=r"Relying on.*is deprecated in v1.2 and will be removed in v1.4"):
        trainer.fit(TestModel())
