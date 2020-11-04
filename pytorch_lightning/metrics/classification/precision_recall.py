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
from typing import Optional, Any

from pytorch_lightning.metrics.classification.utils import _mask_zeros
from pytorch_lightning.metrics.classification.stat_scores import StatScores, _reduce_scores


class Precision(StatScores):
    def compute(self):
        tp = self.tp.float()
        total_pos_pred = _mask_zeros((self.tp + self.fp).float())
        prec_scores = tp / total_pos_pred

        return _reduce_scores(prec_scores, self.tp + self.fn, self.average)


class Recall(StatScores):
    def compute(self):
        tp = self.tp.float()
        total_pos = _mask_zeros((self.tp + self.fn).float())
        rec_scores = tp / total_pos

        return _reduce_scores(rec_scores, self.tp + self.fn, self.average)


class FBeta(StatScores):
    def __init__(
        self,
        beta: float = 1.0,
        average: str = "micro",
        threshold: float = 0.5,
        num_classes: Optional[int] = None,
        logits: bool = False,
        compute_on_step: bool = True,
        dist_sync_on_step: bool = False,
        process_group: Optional[Any] = None,
    ):
        super().__init__(
            threshold=threshold,
            num_classes=num_classes,
            logits=logits,
            average=average,
            compute_on_step=compute_on_step,
            dist_sync_on_step=dist_sync_on_step,
            process_group=process_group,
        )

        self.beta = beta

    def compute(self):
        numerator = (1 + self.beta ** 2) * self.tp.float()
        denominator = numerator + self.beta ** 2 * self.fn.float() + self.fp.float()

        return _reduce_scores(numerator / denominator, self.tp + self.fn, self.average)
