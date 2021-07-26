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
import pytest
import torch

from pytorch_lightning import LightningDataModule, LightningModule, Trainer
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests.helpers import BoringModel, RandomDataset


def test_wrong_train_setting(tmpdir):
    """
    * Test that an error is thrown when no `train_dataloader()` is defined
    * Test that an error is thrown when no `training_step()` is defined
    """
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)

    with pytest.raises(MisconfigurationException, match=r"No `train_dataloader\(\)` method defined."):
        model = BoringModel()
        model.train_dataloader = None
        trainer.fit(model)

    with pytest.raises(MisconfigurationException, match=r"No `training_step\(\)` method defined."):
        model = BoringModel()
        model.training_step = None
        trainer.fit(model)


def test_wrong_configure_optimizers(tmpdir):
    """Test that an error is thrown when no `configure_optimizers()` is defined"""
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)

    with pytest.raises(MisconfigurationException, match=r"No `configure_optimizers\(\)` method defined."):
        model = BoringModel()
        model.configure_optimizers = None
        trainer.fit(model)


def test_fit_val_loop_config(tmpdir):
    """
    When either val loop or val data are missing raise warning
    """
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)

    # no val data has val loop
    with pytest.warns(UserWarning, match=r"you passed in a val_dataloader but have no validation_step"):
        model = BoringModel()
        model.validation_step = None
        trainer.fit(model)

    # has val loop but no val data
    with pytest.warns(UserWarning, match=r"you defined a validation_step but have no val_dataloader"):
        model = BoringModel()
        model.val_dataloader = None
        trainer.fit(model)


def test_test_loop_config(tmpdir):
    """
    When either test loop or test data are missing
    """
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)

    # has test loop but no test data
    with pytest.warns(UserWarning, match=r"you defined a test_step but have no test_dataloader"):
        model = BoringModel()
        model.test_dataloader = None
        trainer.test(model)

    # has test data but no test loop
    with pytest.warns(UserWarning, match=r"you passed in a test_dataloader but have no test_step"):
        model = BoringModel()
        model.test_step = None
        trainer.test(model)


def test_val_loop_config(tmpdir):
    """
    When either validation loop or validation data are missing
    """
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)

    # has val loop but no val data
    with pytest.warns(UserWarning, match=r"you defined a validation_step but have no val_dataloader"):
        model = BoringModel()
        model.val_dataloader = None
        trainer.validate(model)

    # has val data but no val loop
    with pytest.warns(UserWarning, match=r"you passed in a val_dataloader but have no validation_step"):
        model = BoringModel()
        model.validation_step = None
        trainer.validate(model)


@pytest.mark.parametrize("datamodule", [False, True])
def test_trainer_predict_verify_config(tmpdir, datamodule):
    class TestModel(LightningModule):
        def __init__(self):
            super().__init__()
            self.layer = torch.nn.Linear(32, 2)

        def forward(self, x):
            return self.layer(x)

    class TestLightningDataModule(LightningDataModule):
        def __init__(self, dataloaders):
            super().__init__()
            self._dataloaders = dataloaders

        def test_dataloader(self):
            return self._dataloaders

        def predict_dataloader(self):
            return self._dataloaders

    data = [torch.utils.data.DataLoader(RandomDataset(32, 2)), torch.utils.data.DataLoader(RandomDataset(32, 2))]
    if datamodule:
        data = TestLightningDataModule(data)

    model = TestModel()
    trainer = Trainer(default_root_dir=tmpdir)
    results = trainer.predict(model, data)

    assert len(results) == 2
    assert results[0][0].shape == torch.Size([1, 2])

    model.predict_dataloader = None

    with pytest.raises(MisconfigurationException, match="Dataloader not found for `Trainer.predict`"):
        trainer.predict(model)


def test_trainer_manual_optimization_config(tmpdir):
    """Test error message when requesting Trainer features unsupported with manual optimization"""
    model = BoringModel()
    model.automatic_optimization = False

    trainer = Trainer(gradient_clip_val=1.0)
    with pytest.raises(MisconfigurationException, match="Automatic gradient clipping is not supported"):
        trainer.fit(model)

    trainer = Trainer(accumulate_grad_batches=2)
    with pytest.raises(MisconfigurationException, match="Automatic gradient accumulation is not supported"):
        trainer.fit(model)


@pytest.mark.parametrize("stage", ["val", "test"])
def test_error_on_dataloader_idx(tmpdir, stage):
    """ Test error message when dataloader_idx should and should not be present in _step methods """
    trainer = Trainer(default_root_dir=tmpdir, max_epochs=1)
    step_name = 'validation_step' if stage == 'val' else 'test_step'

    class TestModel(BoringModel):

        def validation_step(self, batch, batch_idx, dataloader_idx):
            return super().validation_step(batch, batch_idx)

        def test_step(self, batch, batch_idx, dataloader_idx):
            return super().test_step(batch, batch_idx)

    # _step method has dataloader_idx argument but only one loader and no default
    with pytest.raises(
        MisconfigurationException,
        match=f'You provided only a single {stage}'
        f' dataloader, but have included the `dataloader_idx` in the {step_name} method.'
        ' Either remove the argument or give it a default value i.e. `dataloader_idx=0`.'
    ):
        model = TestModel()
        if stage == 'val':
            trainer.fit(model)
        else:
            trainer.test(model)

    class TestModel(BoringModel):

        def val_dataloader(self):
            return [super().val_dataloader(), super().val_dataloader()]

        def test_dataloader(self):
            return [super().test_dataloader(), super().test_dataloader()]

    # _step methods does not have dataloader_idx argument and multiple loaders
    with pytest.raises(
        MisconfigurationException,
        match=f'You provided multiple {stage} dataloaders,'
        f' but no `dataloader_idx` argument given in {step_name}.'
    ):
        model = TestModel()
        if stage == 'val':
            trainer.fit(model)
        else:
            trainer.test(model)

    # _step method needs a positional argument regardless of number of loaders
    class TestModel(BoringModel):

        def validation_step(self, **kwargs):
            return super().validation_step(**kwargs)

        def test_step(self, **kwargs):
            return super().test_step(**kwargs)

    with pytest.raises(
        MisconfigurationException,
        match=f'Method {step_name} does not work with single `kwargs` argument.'
        ' Either change the signature to .*'
    ):
        model = TestModel()
        if stage == 'val':
            trainer.fit(model)
        else:
            trainer.test(model)
