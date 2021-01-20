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
from typing import Union

import torch
from torch.optim import Optimizer

from pytorch_lightning.plugins.precision_plugin import PrecisionPlugin
from pytorch_lightning.utilities import GradClipAlgorithmType


class NativeAMPPlugin(PrecisionPlugin):

    def __init__(self, trainer=None):
        """
        Integrates native amp into Lightning's internals.
        """
        self.trainer = trainer

    def connect(self, model, optimizers):
        return model, optimizers

    def training_step(self, fx, args):
        with torch.cuda.amp.autocast():
            output = fx(*args)
        return output

    def backward(self, closure_loss, optimizer, opt_idx, *args, **kwargs):
        closure_loss = self.trainer.scaler.scale(closure_loss)

        automatic_optimization = self.trainer.train_loop.automatic_optimization

        # do backward pass
        if automatic_optimization:
            model = self.trainer.get_model()
            model.backward(closure_loss, optimizer, opt_idx)
        else:
            closure_loss.backward(*args, **kwargs)

        # once backward has been applied, release graph
        closure_loss = closure_loss.detach()

        # unscale gradient to allow analyze within `on_after_backward`
        if not self.trainer.train_loop.should_accumulate() and automatic_optimization:
            self.trainer.scaler.unscale_(optimizer)

        return closure_loss

    def clip_gradients(self,
                       optimizer: Optimizer,
                       grad_clip_val: Union[int, float],
                       gradient_clip_algorithm: str,
                       norm_type: Union[float, int]):
        model = self.trainer.get_model()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip_val, norm_type=norm_type)
        if gradient_clip_algorithm == GradClipAlgorithmType.VALUE:
            torch.nn.utils.clip_grad_value_(model.parameters(), clip_value=grad_clip_val)
        elif gradient_clip_algorithm == GradClipAlgorithmType.NORM:
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip_val, norm_type=norm_type)

    @property
    def scaler(self):
        return torch.cuda.amp.GradScaler()

    def optimizer_step(self, trainer, optimizer, closure):
        # native amp does not yet support closures.
        # TODO: pass the closure to the step ASAP
        with trainer.profiler.profile("closure"):
            closure()

        if not self.trainer.train_loop.automatic_optimization:
            trainer.scaler.unscale_(optimizer)
            trainer.call_hook("on_after_backward")

        with trainer.profiler.profile("optimizer_step"):
            trainer.scaler.step(optimizer)
            trainer.scaler.update()
