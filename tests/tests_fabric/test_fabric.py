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
import os
from re import escape
from unittest import mock
from unittest.mock import ANY, call, MagicMock, Mock, PropertyMock

import pytest
import torch
import torch.distributed
import torch.nn.functional
from lightning_utilities.test.warning import no_warning_call
from tests_fabric.helpers.runif import RunIf
from torch import nn
from torch.utils.data import DataLoader, DistributedSampler, RandomSampler, Sampler, SequentialSampler, TensorDataset

from lightning.fabric.fabric import Fabric
from lightning.fabric.plugins import Precision
from lightning.fabric.strategies import (
    DDPStrategy,
    DeepSpeedStrategy,
    ParallelStrategy,
    SingleDeviceStrategy,
    Strategy,
    XLAStrategy,
)
from lightning.fabric.strategies.strategy import _Sharded
from lightning.fabric.utilities.exceptions import MisconfigurationException
from lightning.fabric.utilities.seed import pl_worker_init_function, seed_everything
from lightning.fabric.utilities.warnings import PossibleUserWarning
from lightning.fabric.wrappers import _FabricDataLoader, _FabricModule, _FabricOptimizer


class EmptyFabric(Fabric):
    def run(self):
        pass


class BoringModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.layer = torch.nn.Linear(32, 2, bias=False)

    def forward(self, x):
        x = self.layer(x)
        return torch.nn.functional.mse_loss(x, torch.ones_like(x))


def test_run_input_output():
    """Test that the dynamically patched run() method receives the input arguments and returns the result."""

    class RunFabric(Fabric):

        run_args = ()
        run_kwargs = {}

        def run(self, *args, **kwargs):
            self.run_args = args
            self.run_kwargs = kwargs
            return "result"

    fabric = RunFabric()
    result = fabric.run(1, 2, three=3)
    assert result == "result"
    assert fabric.run_args == (1, 2)
    assert fabric.run_kwargs == {"three": 3}


@mock.patch("lightning.fabric.strategies.ddp.DistributedDataParallel")
@pytest.mark.parametrize("setup_method", ["setup", "setup_module"])
def test_setup_module(ddp_mock, setup_method):
    """Test that the setup method lets the strategy wrap the model, but keeps a reference to the original model."""
    fabric = EmptyFabric(accelerator="cpu", strategy="ddp", devices=2)
    model = nn.Linear(1, 2)
    setup_method = getattr(fabric, setup_method)
    fabric_model = setup_method(model)
    ddp_mock.assert_called_with(module=model, device_ids=ANY)
    assert fabric_model.module == model
    assert fabric_model.weight is model.weight
    assert fabric_model.forward != model.forward


@pytest.mark.parametrize(
    "accelerator, initial_device, target_device",
    [
        ("cpu", "cpu", "cpu"),
        pytest.param("cpu", "cuda:0", "cpu", marks=RunIf(min_cuda_gpus=1)),
        pytest.param("cpu", "mps:0", "cpu", marks=RunIf(mps=True)),
        pytest.param("cuda", "cpu", "cuda:0", marks=RunIf(min_cuda_gpus=1)),
        pytest.param("cuda", "cuda:1", "cuda:0", marks=RunIf(min_cuda_gpus=2)),
        pytest.param("mps", "cpu", "mps:0", marks=RunIf(mps=True)),
    ],
)
@pytest.mark.parametrize("move_to_device", [True, False])
@pytest.mark.parametrize("setup_method", ["setup", "setup_module"])
def test_setup_module_move_to_device(setup_method, move_to_device, accelerator, initial_device, target_device):
    """Test that `move_to_device` leads to parameters being moved to the correct device and that the device
    attributes on the wrapper are updated."""
    initial_device = torch.device(initial_device)
    target_device = torch.device(target_device)
    expected_device = target_device if move_to_device else initial_device

    fabric = EmptyFabric(accelerator=accelerator, devices=1)
    model = nn.Linear(1, 2)
    model.to(initial_device)
    setup_method = getattr(fabric, setup_method)
    fabric_model = setup_method(model, move_to_device=move_to_device)

    # all parameters on the expected device
    assert all(param.device == expected_device for param in model.parameters())
    assert all(param.device == expected_device for param in fabric_model.parameters())

    assert fabric_model.device == expected_device
    assert fabric.device == target_device


@RunIf(min_cuda_gpus=1)
@pytest.mark.parametrize("move_to_device", [True, False])
@pytest.mark.parametrize("setup_method", ["setup", "setup_module"])
def test_setup_module_parameters_on_different_devices(setup_method, move_to_device):
    """Test that a warning is emitted when model parameters are on a different device prior to calling
    `setup()`."""
    device0 = torch.device("cpu")
    device1 = torch.device("cuda", 0)

    fabric = EmptyFabric(accelerator="cuda", devices=1)

    module0 = nn.Linear(1, 2).to(device0)
    module1 = nn.Linear(1, 2).to(device1)
    model = nn.Sequential(module0, module1)

    setup_method = getattr(fabric, setup_method)

    if move_to_device:
        with pytest.warns(PossibleUserWarning, match="has parameters on different devices"):
            fabric_model = setup_method(model, move_to_device=move_to_device)

        # both have the same device now
        assert fabric_model.device == device1
        assert module0.weight.device == module0.bias.device == device1
        assert module1.weight.device == module1.bias.device == device1
    else:
        with no_warning_call(expected_warning=PossibleUserWarning, match="has parameters on different devices"):
            setup_method(model, move_to_device=move_to_device)


def test_setup_module_and_optimizers():
    """Test that `setup()` can handle no optimizers, one optimizer, or multiple optimizers."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer0 = torch.optim.SGD(model.parameters(), lr=0.1)
    optimizer1 = torch.optim.Adam(model.parameters(), lr=0.1)

    # no optimizer
    fabric_model = fabric.setup(model)
    assert isinstance(fabric_model, _FabricModule)
    assert fabric_model.module is model

    # single optimizer
    fabric_model, fabric_optimizer = fabric.setup(model, optimizer0)
    assert isinstance(fabric_model, _FabricModule)
    assert isinstance(fabric_optimizer, _FabricOptimizer)
    assert fabric_model.module is model
    assert fabric_optimizer.optimizer is optimizer0

    # multiple optimizers
    fabric_model, fabric_optimizer0, fabric_optimizer1 = fabric.setup(model, optimizer0, optimizer1)
    assert isinstance(fabric_model, _FabricModule)
    assert isinstance(fabric_optimizer0, _FabricOptimizer)
    assert isinstance(fabric_optimizer1, _FabricOptimizer)
    assert fabric_model.module is model
    assert fabric_optimizer0.optimizer is optimizer0
    assert fabric_optimizer1.optimizer is optimizer1


def test_setup_optimizers():
    """Test that `setup_optimizers()` can handle one or more optimizers."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer0 = torch.optim.SGD(model.parameters(), lr=0.1)
    optimizer1 = torch.optim.Adam(model.parameters(), lr=0.1)

    # single optimizer
    fabric_optimizer = fabric.setup_optimizers(optimizer0)
    assert isinstance(fabric_optimizer, _FabricOptimizer)
    assert fabric_optimizer.optimizer is optimizer0

    # multiple optimizers
    fabric_optimizer0, fabric_optimizer1 = fabric.setup_optimizers(optimizer0, optimizer1)
    assert isinstance(fabric_optimizer0, _FabricOptimizer)
    assert isinstance(fabric_optimizer1, _FabricOptimizer)
    assert fabric_optimizer0.optimizer is optimizer0
    assert fabric_optimizer1.optimizer is optimizer1


def test_setup_twice_fails():
    """Test that calling `setup` with a model or optimizer that is already wrapped fails."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer = torch.optim.Adam(model.parameters())

    fabric_model, fabric_optimizer = fabric.setup(model, optimizer)
    with pytest.raises(ValueError, match="A model should be passed only once to the"):
        fabric.setup(fabric_model, optimizer)

    fabric_model, fabric_optimizer = fabric.setup(model, optimizer)
    with pytest.raises(ValueError, match="An optimizer should be passed only once to the"):
        fabric.setup(model, fabric_optimizer)


def test_setup_module_twice_fails():
    """Test that calling `setup_module` with a model that is already wrapped fails."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)

    fabric_model = fabric.setup_module(model)
    with pytest.raises(ValueError, match="A model should be passed only once to the"):
        fabric.setup_module(fabric_model)


def test_setup_optimizers_twice_fails():
    """Test that calling `setup_module` with a model that is already wrapped fails."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer = torch.optim.Adam(model.parameters())

    fabric_optimizer = fabric.setup_optimizers(optimizer)
    with pytest.raises(ValueError, match="An optimizer should be passed only once to"):
        fabric.setup_optimizers(fabric_optimizer)


@pytest.mark.parametrize("strategy_cls", [DeepSpeedStrategy, XLAStrategy])
def test_setup_optimizers_not_supported(strategy_cls):
    """Test that `setup_optimizers` validates the strategy supports setting up model and optimizers
    independently."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer = torch.optim.Adam(model.parameters())
    fabric._strategy = Mock(spec=strategy_cls)
    with pytest.raises(RuntimeError, match=escape("requires the model and optimizer(s) to be set up jointly through")):
        fabric.setup_optimizers(optimizer)


def test_setup_tracks_num_models():
    """Test that setup() tracks how many times it has setup a model."""
    fabric = EmptyFabric()
    model = nn.Linear(1, 2)
    optimizer = torch.optim.Adam(model.parameters())

    assert fabric._models_setup == 0
    fabric.setup(model, optimizer)
    assert fabric._models_setup == 1

    fabric.setup(model, optimizer)
    assert fabric._models_setup == 2

    fabric.setup_module(model)
    assert fabric._models_setup == 3


def test_setup_dataloaders_unsupported_input():
    """Test that the setup_dataloaders method fails when provided with non-DataLoader objects."""
    fabric = EmptyFabric()
    with pytest.raises(ValueError, match="`setup_dataloaders` requires at least one dataloader"):
        fabric.setup_dataloaders()
    with pytest.raises(TypeError, match="Only PyTorch DataLoader are currently supported"):
        fabric.setup_dataloaders(range(2))  # type: ignore


def test_setup_dataloaders_return_type():
    """Test that the setup method returns the dataloaders wrapped as FabricDataLoader and in the right order."""
    fabric = EmptyFabric()

    # single dataloader
    fabric_dataloader = fabric.setup_dataloaders(DataLoader(range(2)))
    assert isinstance(fabric_dataloader, _FabricDataLoader)

    # multiple dataloaders
    dataset0 = Mock()
    dataset1 = Mock()
    dataloader0 = DataLoader(dataset0)
    dataloader1 = DataLoader(dataset1)
    fabric_dataloader0, fabric_dataloader1 = fabric.setup_dataloaders(dataloader0, dataloader1)
    assert isinstance(fabric_dataloader0, _FabricDataLoader)
    assert isinstance(fabric_dataloader1, _FabricDataLoader)
    assert fabric_dataloader0.dataset is dataset0
    assert fabric_dataloader1.dataset is dataset1


@mock.patch("lightning.fabric.fabric._replace_dunder_methods")
def test_setup_dataloaders_captures_dataloader_arguments(ctx_manager):
    """Test that Fabric intercepts the DataLoader constructor arguments with a context manager in its run
    method."""

    class RunFabric(Fabric):
        def run(self):
            # One for BatchSampler, another for DataLoader
            assert ctx_manager().__enter__.call_count == 2

    RunFabric().run()
    assert ctx_manager().__exit__.call_count == 2


def test_setup_dataloaders_raises_for_unknown_custom_args():
    """Test that an error raises when custom dataloaders with unknown arguments are created from outside Fabric's
    run method."""
    fabric = EmptyFabric()

    class CustomDataLoader(DataLoader):
        def __init__(self, new_arg, *args, **kwargs):
            super().__init__(range(5), *args, **kwargs)

    with pytest.raises(
        MisconfigurationException,
        match=(
            r"Trying to inject custom `Sampler` into the `CustomDataLoader` instance.*"
            r"The missing attributes are \['new_arg'\]"
        ),
    ):
        # The dataloader was not created within the run function, and therefore init args were not intercepted
        dataloader = CustomDataLoader(2, batch_size=2)
        fabric.setup_dataloaders(dataloader)


def test_setup_dataloaders_twice_fails():
    """Test that calling setup_dataloaders with a dataloader that is already wrapped fails."""
    fabric = EmptyFabric()
    dataloader = DataLoader(range(2))
    fabric_dataloader = fabric.setup_dataloaders(dataloader)

    with pytest.raises(ValueError, match="A dataloader should be passed only once to the"):
        fabric.setup_dataloaders(fabric_dataloader)


@mock.patch(
    "lightning.fabric.fabric.Fabric.device",
    new_callable=PropertyMock,
    return_value=torch.device("cuda", 1),
)
def test_setup_dataloaders_move_to_device(fabric_device_mock):
    """Test that the setup configures FabricDataLoader to move the data to the device automatically."""
    fabric = EmptyFabric()
    fabric_dataloaders = fabric.setup_dataloaders(DataLoader(Mock()), DataLoader(Mock()), move_to_device=False)
    assert all(dl.device is None for dl in fabric_dataloaders)
    fabric_device_mock.assert_not_called()

    fabric = EmptyFabric()
    fabric_dataloaders = fabric.setup_dataloaders(DataLoader(Mock()), DataLoader(Mock()), move_to_device=True)
    assert all(dl.device == torch.device("cuda", 1) for dl in fabric_dataloaders)
    fabric_device_mock.assert_called()


def test_setup_dataloaders_distributed_sampler_not_needed():
    """Test that replace_sampler option has no effect when no distributed sampler is needed."""
    custom_sampler = Mock(spec=Sampler)
    dataloader = DataLoader(Mock(), sampler=custom_sampler)

    # keep the custom sampler when not needed to replace
    fabric = EmptyFabric()
    fabric_dataloader = fabric.setup_dataloaders(dataloader, replace_sampler=True)
    assert fabric_dataloader.sampler is custom_sampler


def test_setup_dataloaders_distributed_sampler_shuffle():
    """Test that the DataLoader(shuffle=True|False) setting gets carried over correctly into the distributed
    sampler."""
    fabric = Fabric(accelerator="cpu", strategy="ddp_spawn", devices=2)
    # no fabric.launch(): pretend we are on rank 0 now

    dataset = TensorDataset(torch.arange(8))

    # shuffling turned off
    no_shuffle_dataloaders = [
        DataLoader(dataset),
        DataLoader(dataset, shuffle=False),
        DataLoader(dataset, sampler=SequentialSampler(dataset)),
    ]
    for dataloader in no_shuffle_dataloaders:
        dataloader = fabric.setup_dataloaders(dataloader)
        assert list(t[0].item() for t in iter(dataloader)) == [0, 2, 4, 6]

    # shuffling turned on
    shuffle_dataloaders = [DataLoader(dataset, shuffle=True), DataLoader(dataset, sampler=RandomSampler(dataset))]
    for dataloader in shuffle_dataloaders:
        seed_everything(1)
        dataloader = fabric.setup_dataloaders(dataloader)
        assert list(t[0].item() for t in iter(dataloader)) == [5, 2, 7, 1]


@pytest.mark.parametrize("shuffle", [True, False])
@pytest.mark.parametrize("batch_size", [1, 2, 3])
def test_setup_dataloaders_distributed_sampler_parity(shuffle, batch_size):
    """Test that the distributed sampler setup in Fabric leads to the same sequence of data as in raw PyTorch."""
    torch.manual_seed(1)
    fabric = Fabric(accelerator="cpu", strategy="ddp", devices=2)
    # no fabric.launch(): pretend we are on rank 0 now

    dataset = torch.arange(10)
    torch_dataloader = DataLoader(
        dataset,
        sampler=DistributedSampler(dataset, num_replicas=2, rank=0, shuffle=shuffle),
        batch_size=batch_size,
    )
    fabric_dataloader = DataLoader(dataset, shuffle=shuffle, batch_size=batch_size)
    fabric_dataloader = fabric.setup_dataloaders(fabric_dataloader)

    def fetch_epoch(loader):
        iterator = iter(loader)
        # we fetch 2 batches per epoch
        return torch.cat((next(iterator), next(iterator)))

    # 1st epoch
    # PyTorch users needs to set the epoch, while in Fabric it gets handled automatically
    torch_dataloader.sampler.set_epoch(0)
    torch_data = fetch_epoch(torch_dataloader)
    fabric_data = fetch_epoch(fabric_dataloader)
    assert torch.equal(torch_data, fabric_data)

    # 2nd epoch
    # PyTorch users needs to set the epoch, while in Fabric it gets handled automatically
    torch_dataloader.sampler.set_epoch(1)
    torch_data = fetch_epoch(torch_dataloader)
    fabric_data = fetch_epoch(fabric_dataloader)
    assert torch.equal(torch_data, fabric_data)
    assert torch_dataloader.sampler.epoch == 1
    assert fabric_dataloader._dataloader.sampler.epoch == 1


@mock.patch.dict(os.environ, {}, clear=True)
def test_seed_everything():
    """Test that seed everything is static and sets the worker init function on the dataloader."""
    EmptyFabric.seed_everything(3)

    fabric = EmptyFabric()
    fabric_dataloader = fabric.setup_dataloaders(DataLoader(Mock()))

    assert fabric_dataloader.worker_init_fn.func is pl_worker_init_function
    assert os.environ == {"PL_GLOBAL_SEED": "3", "PL_SEED_WORKERS": "1"}


@pytest.mark.parametrize(
    "strategy",
    [
        "dp",
        "ddp",
        "ddp_spawn",
        pytest.param("ddp_fork", marks=RunIf(skip_windows=True)),
        pytest.param("deepspeed", marks=RunIf(deepspeed=True)),
    ],
)
def test_setup_dataloaders_replace_custom_sampler(strategy):
    """Test that asking to replace a custom sampler results in an error when a distributed sampler would be
    needed."""
    custom_sampler = Mock(spec=Sampler)
    dataloader = DataLoader(Mock(), sampler=custom_sampler)

    # explicitly asking to replace when a custom sampler is already configured raises an exception
    fabric = EmptyFabric(accelerator="cpu", strategy=strategy, devices=2)
    if hasattr(fabric.strategy, "distributed_sampler_kwargs"):
        with pytest.raises(TypeError, match="You seem to have configured a sampler in your DataLoader"):
            fabric.setup_dataloaders(dataloader, replace_sampler=True)

    # setting `replace_sampler=False` leaves the sampler untouched
    fabric_dataloader = fabric.setup_dataloaders(dataloader, replace_sampler=False)
    assert fabric_dataloader.sampler is custom_sampler


@pytest.mark.parametrize(
    "strategy",
    [
        "dp",
        "ddp",
        "ddp_spawn",
        pytest.param("ddp_fork", marks=RunIf(skip_windows=True)),
        pytest.param("deepspeed", marks=RunIf(deepspeed=True)),
    ],
)
@pytest.mark.parametrize("shuffle", [True, False])
def test_setup_dataloaders_replace_standard_sampler(shuffle, strategy):
    """Test that Fabric replaces the default samplers with DistributedSampler automatically."""
    fabric = EmptyFabric(accelerator="cpu", strategy=strategy, devices=2)
    is_distributed = hasattr(fabric.strategy, "distributed_sampler_kwargs")
    fabric_dataloader = fabric.setup_dataloaders(DataLoader(range(3), shuffle=shuffle))
    assert not is_distributed or isinstance(fabric_dataloader.sampler, DistributedSampler)


@pytest.mark.parametrize(
    "accelerator, expected",
    [
        ("cpu", "cpu"),
        pytest.param("cuda", "cuda:0", marks=RunIf(min_cuda_gpus=1)),
        pytest.param("gpu", "cuda:0", marks=RunIf(min_cuda_gpus=1)),
        pytest.param("tpu", "xla:0", marks=RunIf(tpu=True, standalone=True)),
        pytest.param("mps", "mps:0", marks=RunIf(mps=True)),
        pytest.param("gpu", "mps:0", marks=RunIf(mps=True)),
    ],
)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_to_device(accelerator, expected):
    """Test that the to_device method can move various objects to the device determined by the accelerator."""

    class RunFabric(Fabric):
        def run(self):
            expected_device = torch.device(expected)

            # module
            module = torch.nn.Linear(2, 3)
            module = fabric.to_device(module)
            assert all(param.device == expected_device for param in module.parameters())

            # tensor
            tensor = torch.rand(2, 2)
            tensor = fabric.to_device(tensor)
            assert tensor.device == expected_device

            # collection
            collection = {"data": torch.rand(2, 2), "int": 1}
            collection = fabric.to_device(collection)
            assert collection["data"].device == expected_device

    fabric = RunFabric(accelerator=accelerator, devices=1)
    fabric.run()


def test_rank_properties():
    """Test that the rank properties are determined by the strategy."""
    fabric = EmptyFabric()
    fabric._strategy = Mock(spec=Strategy)
    fabric._strategy.world_size = 1000
    assert fabric.world_size == 1000
    fabric._strategy.global_rank = 100
    assert fabric.global_rank == 100
    fabric._strategy.local_rank = 10
    assert fabric.local_rank == 10
    fabric._strategy.node_rank = 1
    assert fabric.node_rank == 1


def test_backward():
    """Test that backward() calls into the precision plugin."""
    fabric = EmptyFabric()
    fabric._precision = Mock(spec=Precision)
    loss = Mock()
    fabric.backward(loss, "arg", keyword="kwarg")
    fabric._precision.backward.assert_called_with(loss, None, "arg", keyword="kwarg")


@RunIf(deepspeed=True, mps=False)
def test_backward_model_input_required():
    """Test that when using deepspeed and multiple models, backward() requires the model as input."""
    fabric = EmptyFabric(strategy="deepspeed")

    model0 = nn.Linear(1, 2)
    model1 = nn.Linear(1, 2)

    optimizer0 = torch.optim.Adam(model0.parameters())
    optimizer1 = torch.optim.Adam(model1.parameters())

    fabric._strategy.setup_module_and_optimizers = lambda *args: args

    fabric.setup(model0, optimizer0)
    fabric.setup(model1, optimizer1)

    loss = model0(torch.randn(1, 1)).sum()

    with pytest.raises(ValueError, match="please provide the model used to perform"):
        fabric.backward(loss)


def test_autocast():
    """Test that the Fabric autocast context manager lets the precision plugin handle casting."""
    fabric = EmptyFabric()
    fabric._precision.forward_context = MagicMock()

    fabric._precision.forward_context().__enter__.assert_not_called()
    with fabric.autocast():
        fabric._precision.forward_context().__enter__.assert_called()
    fabric._precision.forward_context().__exit__.assert_called()


def test_no_backward_sync():
    """Test that `Fabric.no_backward_sync()` validates the strategy and model is compatible."""
    fabric = EmptyFabric()
    model = nn.Linear(3, 3)
    with pytest.raises(TypeError, match="You need to set up the model first"):
        with fabric.no_backward_sync(model):
            pass

    model = fabric.setup(model)

    # pretend that the strategy does not support skipping backward sync
    fabric._strategy = Mock(spec=ParallelStrategy, _backward_sync_control=None)
    with pytest.warns(PossibleUserWarning, match="The `ParallelStrategy` does not support skipping the"):
        with fabric.no_backward_sync(model):
            pass

    # for single-device strategies, it becomes a no-op without warning
    fabric._strategy = Mock(spec=SingleDeviceStrategy, _backward_sync_control=MagicMock())
    with fabric.no_backward_sync(model):
        pass
    fabric._strategy._backward_sync_control.no_backward_sync.assert_not_called()

    # pretend that the strategy supports skipping backward sync
    fabric._strategy = Mock(_backward_sync_control=MagicMock())
    # disabling the context manager makes it a no-op
    with fabric.no_backward_sync(model, enabled=False):
        pass
    fabric._strategy._backward_sync_control.no_backward_sync.assert_not_called()
    # when enabld, the wrapped module gets passed down
    with fabric.no_backward_sync(model):
        pass
    fabric._strategy._backward_sync_control.no_backward_sync.assert_called_once_with(model._forward_module)


def test_launch_without_function():
    """Test the various ways `Fabric.launch()` can be called."""

    # default: no launcher, single process
    fabric = Fabric()
    with mock.patch("lightning.fabric.fabric._do_nothing") as nothing:
        fabric.launch()
    nothing.assert_called()

    # with a launcher on the strategy
    fabric = Fabric()
    fabric._strategy._launcher = Mock()
    fabric.launch()
    fabric._strategy._launcher.launch.assert_called()


def test_launch_with_function():
    """Test the various ways `Fabric.launch(function)` can be called."""

    def fn_without_args():
        pass

    fabric = Fabric()
    with pytest.raises(TypeError, match="The function passed to .* needs to take at least one argument"):
        fabric.launch(fn_without_args)

    def fn_with_one_arg(arg):
        assert isinstance(arg, Fabric)
        fn_with_one_arg.called = True

    fabric = Fabric()
    fabric.launch(fn_with_one_arg)
    assert fn_with_one_arg.called


@mock.patch.dict(os.environ, {"LT_CLI_USED": "1"})  # pretend we are using the CLI
def test_launch_and_cli_not_allowed():
    fabric = Fabric()
    with pytest.raises(RuntimeError, match=escape("Calling  `.launch()` again is not allowed")):
        fabric.launch()


@mock.patch.dict(os.environ, {"LT_CLI_USED": "1"})  # pretend we are using the CLI
def test_overridden_run_and_cli_not_allowed():
    class FabricWithRun(Fabric):
        def run(self):
            pass

    with pytest.raises(TypeError, match=escape("Overriding `Fabric.run()` and launching from the CLI is not allowed")):
        FabricWithRun()


def test_module_sharding_context():
    """Test that the sharding context manager gets applied when the strategy supports it and is a no-op
    otherwise."""
    fabric = EmptyFabric()
    fabric._strategy = MagicMock(spec=DDPStrategy, module_sharded_context=Mock())
    with fabric.sharded_model():
        pass
    fabric._strategy.module_sharded_context.assert_not_called()

    fabric._strategy = MagicMock(spec=_Sharded)
    with fabric.sharded_model():
        pass
    fabric._strategy.module_sharded_context.assert_called_once()


def test_callbacks_input():
    """Test the various ways in which callbacks can be registered with Fabric."""
    callback0 = Mock()
    callback1 = Mock()

    # single callback
    fabric = Fabric(callbacks=callback0)
    assert fabric._callbacks == [callback0]

    # multiple callbacks
    fabric = Fabric(callbacks=[callback0, callback1])
    assert fabric._callbacks == [callback0, callback1]


def test_call():
    """Test that `fabric.call` triggers the callback implementations."""
    callback0 = Mock()
    callback1 = Mock()
    fabric = Fabric(callbacks=[callback0, callback1])

    # No arguments
    fabric.call("on_train_end")
    callback0.on_train_end.assert_called_once()
    callback1.on_train_end.assert_called_once()

    # Optional arguments
    fabric.call("on_train_end", "positional", keyword="keyword")
    callback0.on_train_end.assert_called_with("positional", keyword="keyword")
    callback1.on_train_end.assert_called_with("positional", keyword="keyword")

    # Some callbacks don't implement the requested hook
    callback0 = Mock()
    callback1 = Mock(spec_set={})  # `on_train_end` not defined for this callback
    fabric = Fabric(callbacks=[callback0, callback1])
    fabric.call("on_train_end")
    callback0.on_train_end.assert_called_once()
    assert not callback1.mock_calls  # no methods were called on callback1

    # Skip callback attributes that are not callable
    callback = Mock(not_a_method=1)
    fabric = Fabric(callbacks=[callback])
    with pytest.warns(UserWarning, match="Skipping the callback `Mock.not_a_method`"):
        fabric.call("not_a_method")
    assert not callback1.mock_calls


def test_loggers_input():
    """Test the various ways in which loggers can be registered with Fabric."""
    logger0 = Mock()
    logger1 = Mock()

    # no logger
    fabric = Fabric(loggers=None)
    assert fabric._loggers == []
    fabric = Fabric(loggers=[])
    assert fabric._loggers == []

    # single logger
    fabric = Fabric(loggers=logger0)
    assert fabric._loggers == [logger0]

    # multiple loggers
    fabric = Fabric(loggers=[logger0, logger1])
    assert fabric._loggers == [logger0, logger1]


def test_log():
    """Test that `fabric.log` sends the metrics to each logger."""

    logger0 = Mock()
    logger1 = Mock()
    fabric = Fabric(loggers=[logger0, logger1])

    fabric.log("test", 1)
    logger0.log_metrics.assert_called_with(metrics={"test": 1}, step=None)
    logger1.log_metrics.assert_called_with(metrics={"test": 1}, step=None)

    fabric.log("test", 2, step=15)
    logger0.log_metrics.assert_called_with(metrics={"test": 2}, step=15)
    logger1.log_metrics.assert_called_with(metrics={"test": 2}, step=15)


def test_log_dict():
    """Test that `fabric.log_dict` sends the metrics dict to each logger."""

    logger0 = Mock()
    logger1 = Mock()
    fabric = Fabric(loggers=[logger0, logger1])

    fabric.log_dict({"foo": 1, "bar": 2}, step=None)
    logger0.log_metrics.assert_called_with(metrics={"foo": 1, "bar": 2}, step=None)
    logger1.log_metrics.assert_called_with(metrics={"foo": 1, "bar": 2}, step=None)

    fabric.log_dict({"foo": 3, "bar": 4}, step=15)
    logger0.log_metrics.assert_called_with(metrics={"foo": 3, "bar": 4}, step=15)
    logger1.log_metrics.assert_called_with(metrics={"foo": 3, "bar": 4}, step=15)


def test_log_dict_input_parsing():
    """Test validation of input data types and preprocessing."""
    logger = Mock()
    fabric = Fabric(loggers=[logger])

    # Tensor scalar, 0 dims
    fabric.log("log", torch.tensor(1))
    logger.log_metrics.assert_called_with(metrics={"log": 1}, step=None)
    fabric.log_dict({"log_dict": torch.tensor(1)})
    logger.log_metrics.assert_called_with(metrics={"log_dict": 1}, step=None)

    # Tensor scalar, 1 dims
    fabric.log("log", torch.tensor([2]))
    logger.log_metrics.assert_called_with(metrics={"log": 2}, step=None)
    fabric.log_dict({"log_dict": torch.tensor([2])})
    logger.log_metrics.assert_called_with(metrics={"log_dict": 2}, step=None)

    # Tensor, multiple dims
    with pytest.raises(ValueError, match="it cannot be converted to a scalar."):
        fabric.log("log", torch.tensor([3, 4]))

    with pytest.raises(ValueError, match="it cannot be converted to a scalar."):
        fabric.log_dict({"log_dict": torch.tensor([3, 4])})


@pytest.mark.parametrize("setup", [True, False])
def test_save_wrapped_objects(setup, tmp_path):
    """Test that when modules and optimizers are in the state, they get unwrapped properly."""
    fabric = Fabric()
    save_checkpoint_mock = Mock()
    fabric.strategy.save_checkpoint = save_checkpoint_mock

    unwrapped_model = BoringModel()
    unwrapped_optimizer = torch.optim.Adam(unwrapped_model.parameters())

    if setup:
        model, optimizer = fabric.setup(unwrapped_model, unwrapped_optimizer)
        assert isinstance(model, _FabricModule)
        assert isinstance(optimizer, _FabricOptimizer)
    else:
        model, optimizer = unwrapped_model, unwrapped_optimizer

    anything = {"cocofruit": 1}
    state = {"model": model, "optimizer": optimizer, "anything": anything}
    expected = {"model": unwrapped_model, "optimizer": unwrapped_optimizer, "anything": anything}
    fabric.save(tmp_path, state)
    save_checkpoint_mock.assert_called_with(state=expected, path=tmp_path)


def test_barrier():
    """Test that `Fabric.barrier()` calls into the strategy."""
    fabric = Fabric()
    fabric._strategy = Mock()
    fabric.barrier("test")
    fabric._strategy.barrier.assert_called_once_with(name="test")


def test_broadcast():
    """Test that `Fabric.broadcast()` calls into the strategy."""
    fabric = Fabric()
    fabric._strategy = Mock()
    fabric.broadcast(torch.tensor(1), src=2)
    fabric._strategy.broadcast.assert_called_once_with(torch.tensor(1), src=2)


def test_all_gather():
    """Test that `Fabric.all_gather()` applies itself to collections and calls into the strategy."""
    fabric = Fabric()
    fabric._strategy = Mock(root_device=torch.device("cpu"))
    defaults = dict(group=None, sync_grads=False)

    # single tensor
    fabric.all_gather(torch.tensor(1))
    fabric._strategy.all_gather.assert_called_once_with(torch.tensor(1), **defaults)
    fabric._strategy.reset_mock()

    # list
    fabric.all_gather([torch.tensor(2), torch.tensor(3), "string"])
    fabric._strategy.all_gather.assert_has_calls([call(torch.tensor(2), **defaults), call(torch.tensor(3), **defaults)])
    fabric._strategy.reset_mock()

    # dict
    fabric.all_gather({"a": torch.tensor(4), "b": [torch.tensor(5)], "c": "string"})
    fabric._strategy.all_gather.assert_has_calls([call(torch.tensor(4), **defaults), call(torch.tensor(5), **defaults)])


def test_all_reduce():
    """Test that `Fabric.all_reduce()` applies itself to collections and calls into the strategy."""
    fabric = Fabric()
    fabric._strategy = Mock(root_device=torch.device("cpu"))
    defaults = dict(group=None, reduce_op="mean")

    # single tensor
    fabric.all_reduce(torch.tensor(1))
    fabric._strategy.all_reduce.assert_called_once_with(torch.tensor(1), **defaults)
    fabric._strategy.reset_mock()

    # list
    fabric.all_reduce([torch.tensor(2), torch.tensor(3), "string"])
    fabric._strategy.all_reduce.assert_has_calls([call(torch.tensor(2), **defaults), call(torch.tensor(3), **defaults)])
    fabric._strategy.reset_mock()

    # dict
    fabric.all_reduce({"a": torch.tensor(4), "b": [torch.tensor(5)], "c": "string"})
    fabric._strategy.all_reduce.assert_has_calls([call(torch.tensor(4), **defaults), call(torch.tensor(5), **defaults)])
