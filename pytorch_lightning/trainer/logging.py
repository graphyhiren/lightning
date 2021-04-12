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

from abc import ABC

import torch

from pytorch_lightning.utilities.exceptions import MisconfigurationException


class TrainerLoggingMixin(ABC):

    def metrics_to_scalars(self, metrics):
        new_metrics = {}
        # TODO: this is duplicated in MetricsHolder. should be unified
        for k, v in metrics.items():
            if isinstance(v, torch.Tensor):
                if v.numel() != 1:
                    raise MisconfigurationException(
                        f"The metric `{k}` does not contain a single element"
                        f" thus it cannot be converted to float. Found `{v}`"
                    )
                v = v.item()

            if isinstance(v, dict):
                v = self.metrics_to_scalars(v)

            new_metrics[k] = v

        return new_metrics
