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
from unittest import mock

import pytest

from pytorch_lightning.plugins.precision.deepspeed import DeepSpeedPrecisionPlugin
from pytorch_lightning.trainer.trainer import Trainer
from pytorch_lightning.utilities.exceptions import MisconfigurationException


def test_invalid_precision_with_deepspeed_precision():
    with pytest.raises(ValueError, match="is not supported. `precision` must be one of"):
        DeepSpeedPrecisionPlugin(precision=64, amp_type="native")


def test_deepspeed_precision_apex_not_installed(monkeypatch):
    import pytorch_lightning.plugins.precision.deepspeed as deepspeed_apex

    monkeypatch.setattr(deepspeed_apex, "_APEX_AVAILABLE", False)
    with pytest.raises(MisconfigurationException, match="You have asked for Apex AMP but you have not installed it."):
        DeepSpeedPrecisionPlugin(precision=16, amp_type="apex")


@mock.patch("pytorch_lightning.plugins.precision.deepspeed._APEX_AVAILABLE", return_value=True)
def test_deepspeed_precision_apex_default_level(_):
    trainer = Trainer(strategy="deepspeed", amp_backend="apex", amp_level=None)
    precision_plugin = trainer.strategy.precision_plugin
    assert isinstance(precision_plugin, DeepSpeedPrecisionPlugin)
    assert precision_plugin.amp_level == "O2"
