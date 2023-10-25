from unittest import mock
from unittest.mock import Mock, call

import torch
from lightning.fabric.utilities.throughput_monitor import measure_flops
from lightning.pytorch import Trainer
from lightning.pytorch.callbacks.throughput_monitor import ThroughputMonitor
from lightning.pytorch.demos.boring_classes import BoringModel

from tests_pytorch.helpers.runif import RunIf


@RunIf(min_torch="2.1")
def test_measure_flops():
    with torch.device("meta"):
        model = BoringModel()
        x = torch.randn(2, 32)
    model_fwd = lambda: model(x)

    fwd_flops = measure_flops(model, model_fwd)
    assert isinstance(fwd_flops, int)

    fwd_and_bwd_flops = measure_flops(model, model_fwd, model.loss)
    assert isinstance(fwd_and_bwd_flops, int)
    assert fwd_flops < fwd_and_bwd_flops


def test_throughput_monitor(tmp_path):
    logger_mock = Mock()
    logger_mock.save_dir = tmp_path
    monitor = ThroughputMonitor(length_fn=lambda x: 2, batch_size_fn=lambda x: 3, window_size=3, time_unit="seconds")
    model = BoringModel()
    model.flops_per_batch = 10
    trainer = Trainer(
        devices=1,
        logger=logger_mock,
        callbacks=monitor,
        max_steps=5,
        val_check_interval=2,
        num_sanity_val_steps=2,
        enable_checkpointing=False,
        enable_model_summary=False,
        enable_progress_bar=False,
    )
    # these timing results are meant to precisely match the `test_throughput_monitor` test in fabric
    timings = [0.0, 1.5, 2.5, 0.0, 0.2, 3.5, 4.5, 0.0, 0.2, 5.5, 6.5]
    with mock.patch(
        "lightning.pytorch.callbacks.throughput_monitor._get_flops_available", return_value=100
    ), mock.patch("time.perf_counter", side_effect=timings):
        trainer.fit(model)

    assert logger_mock.log_metrics.mock_calls == [
        call(metrics={"time/train": 1.5, "time/val": 0.0, "time/total": 1.5, "samples": 3, "epoch": 0}, step=0),
        call(metrics={"time/train": 2.5, "time/val": 0.0, "time/total": 2.5, "samples": 6, "epoch": 0}, step=1),
        call(metrics={"time/train": 3.5, "time/val": 0.2, "time/total": 3.7, "samples": 9, "epoch": 0}, step=2),
        call(
            metrics={
                "batches_per_sec": 1.0,
                "samples_per_sec": 3.0,
                "device/batches_per_sec": 1.0,
                "device/samples_per_sec": 3.0,
                "items_per_sec": 6.0,
                "device/items_per_sec": 6.0,
                "flops_per_sec": 10.0,
                "device/flops_per_sec": 10.0,
                "device/mfu": 0.1,
                "time/train": 4.5,
                "time/val": 0.2,
                "time/total": 4.7,
                "samples": 12,
                "epoch": 0,
            },
            step=3,
        ),
        call(
            metrics={
                "batches_per_sec": 1.0,
                "samples_per_sec": 3.0,
                "device/batches_per_sec": 1.0,
                "device/samples_per_sec": 3.0,
                "items_per_sec": 6.0,
                "device/items_per_sec": 6.0,
                "flops_per_sec": 10.0,
                "device/flops_per_sec": 10.0,
                "device/mfu": 0.1,
                "time/train": 5.5,
                "time/val": 0.4,
                "time/total": 5.9,
                "samples": 15,
                "epoch": 0,
            },
            step=4,
        ),
    ]


# TODO: add gradient accumulation test