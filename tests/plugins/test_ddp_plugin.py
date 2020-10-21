from pytorch_lightning.callbacks import Callback
from tests.base.boring_model import BoringModel
from pytorch_lightning import accelerators, Trainer
from pytorch_lightning.plugins.ddp_plugin import DDPPlugin
import pytest
import os
from unittest import mock


@mock.patch('torch.cuda.device_count', return_value=2)
@pytest.mark.parametrize(['ddp_backend', 'gpus', 'num_processes'],
                         [('ddp_cpu', None, None), ('ddp', 2, 0), ('ddp2', 2, 0), ('ddp_spawn', 2, 0)])
def test_ddp_choice_default_ddp_cpu(tmpdir, ddp_backend, gpus, num_processes):

    class CB(Callback):
        def on_fit_start(self, trainer, pl_module):
            assert isinstance(trainer.accelerator_backend.ddp_plugin, DDPPlugin)
            raise SystemExit()

    model = BoringModel()
    trainer = Trainer(
        fast_dev_run=True,
        gpus=gpus,
        num_processes=num_processes,
        distributed_backend=ddp_backend,
        callbacks=[CB()]
    )

    with pytest.raises(SystemExit):
        trainer.fit(model)


@mock.patch('torch.cuda.device_count', return_value=2)
@pytest.mark.parametrize(['ddp_backend', 'gpus', 'num_processes'],
                         [('ddp_cpu', None, None), ('ddp', 2, 0), ('ddp2', 2, 0), ('ddp_spawn', 2, 0)])
def test_ddp_choice_custom_ddp_cpu(tmpdir, ddp_backend, gpus, num_processes):
    class MyDDP(DDPPlugin):
        pass

    class CB(Callback):
        def on_fit_start(self, trainer, pl_module):
            assert isinstance(trainer.accelerator_backend.ddp_plugin, MyDDP)
            raise SystemExit()

    model = BoringModel()
    trainer = Trainer(
        fast_dev_run=True,
        gpus=gpus,
        num_processes=num_processes,
        distributed_backend=ddp_backend,
        plugins=[MyDDP()],
        callbacks=[CB()]
    )

    with pytest.raises(SystemExit):
        trainer.fit(model)
