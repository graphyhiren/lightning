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
from typing import Iterable

import pytest
from fiftyone.utils import torch
from torch.utils.data import BatchSampler, SequentialSampler

from lightning.fabric.utilities.data import has_len
from lightning.pytorch import LightningModule, seed_everything, Trainer
from lightning.pytorch.overrides.distributed import _IndexBatchSamplerWrapper, UnrepeatedDistributedSampler


def test_params_synced_during_nonfit():
    class MyModel(LightningModule):
        def __init__(self):
            super().__init__()
            self.layer = torch.nn.Linear(1, 1)
            print(self.local_rank, "INIT", self.layer.weight.data, self.layer.bias.data)

        def test_step(self, batch, batch_idx):
            print(self.local_rank, "FWD", self.layer.weight.data, self.layer.bias.data)

    model = MyModel()
    trainer = Trainer(
        limit_test_batches=1,
        barebones=True,
        devices=2,
        accelerator="cpu",
        strategy="ddp_spawn",
    )
    trainer.test(model, [0])


@pytest.mark.parametrize("shuffle", [False, True])
def test_unrepeated_distributed_sampler(shuffle):
    """Test each rank will receive a different number of elements."""

    seed_everything(42)
    world_size = 4
    samplers = []
    dataset = range(103)
    for rank in range(world_size):
        samplers.append(UnrepeatedDistributedSampler(dataset, rank=rank, num_replicas=world_size, shuffle=shuffle))

    indices = [list(s) for s in samplers]
    assert len(indices[0]) == 26
    assert len(indices[1]) == 26
    assert len(indices[2]) == 26
    assert len(indices[3]) == 25

    assert indices[0][-1] == 18 if shuffle else 100
    assert indices[1][-1] == 30 if shuffle else 101
    assert indices[2][-1] == 29 if shuffle else 102
    assert indices[3][-1] == 35 if shuffle else 99


def test_index_batch_sampler():
    """Test `IndexBatchSampler` properly extracts indices."""
    dataset = range(15)
    sampler = SequentialSampler(dataset)
    batch_sampler = BatchSampler(sampler, 3, False)
    index_batch_sampler = _IndexBatchSamplerWrapper(batch_sampler)

    assert isinstance(index_batch_sampler, BatchSampler)
    assert batch_sampler.batch_size == index_batch_sampler.batch_size
    assert batch_sampler.drop_last == index_batch_sampler.drop_last
    assert batch_sampler.sampler is sampler
    assert index_batch_sampler.sampler is sampler
    assert list(index_batch_sampler) == index_batch_sampler.seen_batch_indices
    assert list(index_batch_sampler) == list(batch_sampler)

    assert isinstance(index_batch_sampler, Iterable)
    assert has_len(index_batch_sampler)

    iterator = iter(index_batch_sampler)
    assert index_batch_sampler.seen_batch_indices == []
    b0 = next(iterator)
    assert b0 == [0, 1, 2]
    assert index_batch_sampler.seen_batch_indices == [b0]
    b1 = next(iterator)
    assert b1 == [3, 4, 5]
    assert index_batch_sampler.seen_batch_indices == [b0, b1]
