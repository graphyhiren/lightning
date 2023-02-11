from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Union

import torch
from lightning_utilities import WarningCache

from lightning.fabric.utilities import move_data_to_device
from lightning.pytorch.loops.fetchers import _DataFetcher
from lightning.pytorch.loops.loop import _Loop
from lightning.pytorch.loops.progress import Progress
from lightning.pytorch.loops.utilities import _select_data_fetcher
from lightning.pytorch.overrides.distributed import IndexBatchSamplerWrapper
from lightning.pytorch.strategies import DDPSpawnStrategy
from lightning.pytorch.trainer.supporters import _Sequential
from lightning.pytorch.utilities.exceptions import MisconfigurationException
from lightning.pytorch.utilities.types import _PREDICT_OUTPUT


class _PredictionLoop(_Loop):
    """Top-level loop where prediction starts."""

    def __init__(self) -> None:
        super().__init__()
        self.epoch_batch_indices: List[
            List[List[int]]
        ] = []  # dataloaders x batches x samples. used by PredictionWriter
        self.current_batch_indices: List[int] = []  # used by PredictionWriter
        self.batch_progress = Progress()

        self._warning_cache = WarningCache()
        self._data_fetcher: Optional[_DataFetcher] = None
        self._results = None  # for `trainer._results` access
        self._predictions: List[List[Any]] = []  # dataloaders x batches
        self._return_predictions = False

    @property
    def return_predictions(self) -> bool:
        """Whether to return the predictions or not."""
        return self._return_predictions

    @return_predictions.setter
    def return_predictions(self, return_predictions: Optional[bool] = None) -> None:
        # `DDPSpawnStrategy` plugins and derivatives don't support return predictions.
        is_ddp_spawn = isinstance(self.trainer.strategy, DDPSpawnStrategy)
        if return_predictions and is_ddp_spawn:
            raise MisconfigurationException(
                "`return_predictions` should be set to `False` when using the `DDPSpawnStrategy` or children class. "
                f"Found {return_predictions} with strategy {type(self.trainer.strategy)}."
            )
        # For non `DDPSpawnStrategy` plugin, the `return_predictions` is True by default unless user decide otherwise.
        self._return_predictions = not is_ddp_spawn if return_predictions is None else return_predictions

    @property
    def predictions(self) -> List[Any]:
        """The cached predictions."""
        if self._predictions == []:
            return self._predictions
        return self._predictions[0] if self.num_dataloaders == 1 else self._predictions

    @property
    def num_dataloaders(self) -> int:
        """Returns the number of prediction dataloaders."""
        # FIXME(carlos): can I remove this?
        combined_loader = self.trainer.predict_dataloaders
        assert combined_loader is not None
        return len(combined_loader._loaders_flattened)

    @property
    def current_dataloader_idx(self) -> int:
        """Returns the index of the current dataloader."""
        combined_loader = self.trainer.predict_dataloaders
        assert combined_loader is not None
        if isinstance(combined_loader._iterator, _Sequential):
            return combined_loader._iterator._iterator_idx
        return 0

    @property
    def current_dataloader(self) -> Iterable:
        """Returns the current dataloader."""
        combined_loader = self.trainer.predict_dataloaders
        assert combined_loader is not None
        return combined_loader._loaders_flattened[self.current_dataloader_idx]

    @property
    def max_batches(self) -> List[Union[int, float]]:
        """The max number of batches this loop will run for each dataloader."""
        return self.trainer.num_predict_batches

    @property
    def skip(self) -> bool:
        return sum(self.max_batches) == 0

    def run(self) -> Optional[_PREDICT_OUTPUT]:
        if self.skip:
            return None
        self.reset()
        self.on_run_start()

        while True:
            try:
                batch_idx, batch = next(self._data_fetcher)
                dataloader_idx = self.current_dataloader_idx
                if batch_idx >= self.max_batches[dataloader_idx]:
                    break
                self._predict_step(batch, batch_idx, dataloader_idx)
                self._restarting = False
            except StopIteration:
                break
        self._restarting = False
        return self.on_run_end()

    def reset(self) -> None:
        """Resets the internal state of the loop for a new run."""
        # FIXME(carlos): move these two somewhere else
        # _set_sampler_epoch(dataloader, self.trainer.fit_loop.epoch_progress.current.processed)
        # self.trainer.strategy.process_dataloader(dataloader)

        combined_loader = self.trainer.predict_dataloaders
        assert self.trainer.predict_dataloaders is not None
        iter(combined_loader)
        assert isinstance(combined_loader._iterator, _Sequential)

        # FIXME(carlos): once we support regular dataloader, we wont need this
        num_dataloaders = self.num_dataloaders
        self.epoch_batch_indices = [[] for _ in range(num_dataloaders)]
        self._predictions = [[] for _ in range(num_dataloaders)]

        self.batch_progress.reset_on_run()

        data_fetcher = _select_data_fetcher(self.trainer)
        data_fetcher.setup(combined_loader)
        iter(data_fetcher)  # creates the iterator inside the fetcher
        # add the previous `fetched` value to properly track `is_last_batch` with no prefetching
        data_fetcher.fetched += self.batch_progress.current.ready
        data_fetcher._start_profiler = self._on_before_fetch
        data_fetcher._stop_profiler = self._on_after_fetch
        self._data_fetcher = data_fetcher

    def on_run_start(self) -> None:
        """Calls ``_on_predict_model_eval``, ``_on_predict_start`` and ``_on_predict_epoch_start`` hooks."""
        self.trainer._call_lightning_module_hook("on_predict_model_eval")
        self.trainer.lightning_module.zero_grad()
        self._on_predict_start()
        self._on_predict_epoch_start()

    def on_run_end(self) -> Optional[_PREDICT_OUTPUT]:
        """Calls ``on_predict_epoch_end`` and ``on_predict_end`` hooks and returns results from all dataloaders."""
        results = self._on_predict_epoch_end()
        self._on_predict_end()
        return results

    def teardown(self) -> None:
        if self._data_fetcher is not None:
            self._data_fetcher.teardown()
            self._data_fetcher = None

    def _predict_step(self, batch: Any, batch_idx: int, dataloader_idx: int) -> None:
        """Runs the actual predict step together with all the necessary bookkeeping and the hooks tied to the
        predict step.

        Args:
            batch: the current batch to run the prediction on
            batch_idx: the index of the current batch
            dataloader_idx: the index of the dataloader producing the current batch
        """
        batch = self.trainer.lightning_module._on_before_batch_transfer(batch, dataloader_idx=dataloader_idx)
        batch = self.trainer._call_strategy_hook("batch_to_device", batch, dataloader_idx=dataloader_idx)

        self.batch_progress.increment_ready()

        any_on_epoch = self._store_data_for_prediction_writer(batch_idx, dataloader_idx)

        self.trainer._call_callback_hooks("on_predict_batch_start", batch, batch_idx, dataloader_idx)
        self.trainer._call_lightning_module_hook("on_predict_batch_start", batch, batch_idx, dataloader_idx)

        self.batch_progress.increment_started()

        # configure step_kwargs
        step_kwargs = self._build_kwargs(batch, batch_idx, dataloader_idx if self.num_dataloaders > 1 else None)
        predictions = self.trainer._call_strategy_hook("predict_step", *step_kwargs.values())

        self.batch_progress.increment_processed()

        if predictions is None:
            self._warning_cache.warn("predict returned None if it was on purpose, ignore this warning...")

        self.trainer._call_callback_hooks("on_predict_batch_end", predictions, batch, batch_idx, dataloader_idx)
        self.trainer._call_lightning_module_hook("on_predict_batch_end", predictions, batch, batch_idx, dataloader_idx)

        self.batch_progress.increment_completed()

        if self._return_predictions or any_on_epoch:
            self._predictions[dataloader_idx].append(move_data_to_device(predictions, torch.device("cpu")))

    def _build_kwargs(self, batch: Any, batch_idx: int, dataloader_idx: Optional[int]) -> Dict[str, Any]:
        """Assembles the keyword arguments for the ``predict_step``

        Args:
            batch: the current batch to run the prediction on
            batch_idx: the index of the current batch
            dataloader_idx: the index of the dataloader producing the current batch. None if not multiple dataloaders.

        Returns:
            the dictionary containing all the keyboard arguments for the predict step
        """
        step_kwargs = OrderedDict([("batch", batch), ("batch_idx", batch_idx)])
        if dataloader_idx is not None:
            step_kwargs["dataloader_idx"] = dataloader_idx
        return step_kwargs

    def _get_batch_indices(self, dataloader: object) -> List[List[int]]:  # batches x samples
        """Returns a reference to the seen batch indices if the dataloader has a batch sampler wrapped by our
        :class:`~lightning.pytorch.overrides.distributed.IndexBatchSamplerWrapper`."""
        batch_sampler = getattr(dataloader, "batch_sampler", None)
        if not isinstance(batch_sampler, IndexBatchSamplerWrapper):
            self._warning_cache.warn(
                f"Couldn't infer the batch indices fetched from your dataloader: `{type(dataloader).__name__}`"
            )
            return []
        seen_batch_indices = batch_sampler.seen_batch_indices
        # TODO(carmocca): this could be avoided
        # we need to truncate the list because `IndexBatchSamplerWrapper` computes all indices on `__iter__`
        seen_batch_indices = seen_batch_indices[: (self.batch_progress.current.completed + 1)]
        return seen_batch_indices

    def _store_data_for_prediction_writer(self, batch_idx: int, dataloader_idx: int) -> bool:
        prediction_writer_callbacks = self.trainer.prediction_writer_callbacks
        any_on_epoch = any(cb.interval.on_epoch for cb in prediction_writer_callbacks)
        any_on_batch = any(cb.interval.on_batch for cb in prediction_writer_callbacks)
        if any_on_batch or any_on_epoch:
            dataloader = self.current_dataloader
            batch_indices = self._get_batch_indices(dataloader)
            if not batch_indices:
                # this is only available with `IndexBatchSamplerWrapper`, but it's only used on DataLoaders, if this is
                # reached, it's likely because a non-DataLoader was passed
                return any_on_epoch
            batch_indices = batch_indices[batch_idx]
            if any_on_epoch:
                self.epoch_batch_indices[dataloader_idx].append(batch_indices)
            if any_on_batch:
                self.current_batch_indices = batch_indices
        return any_on_epoch

    def _on_before_fetch(self) -> None:
        self.trainer.profiler.start(
            f"[{self.__class__.__name__}].predict_dataloader_idx_{self.current_dataloader_idx}_next"
        )

    def _on_after_fetch(self) -> None:
        self.trainer.profiler.stop(
            f"[{self.__class__.__name__}].predict_dataloader_idx_{self.current_dataloader_idx}_next"
        )

    def _on_predict_start(self) -> None:
        """Calls ``on_predict_start`` hooks."""
        self.trainer._call_callback_hooks("on_predict_start")
        self.trainer._call_lightning_module_hook("on_predict_start")
        self.trainer._call_strategy_hook("on_predict_start")

    def _on_predict_epoch_start(self) -> None:
        """Calls ``on_predict_epoch_start`` hooks."""
        self.trainer._call_callback_hooks("on_predict_epoch_start")
        self.trainer._call_lightning_module_hook("on_predict_epoch_start")

    def _on_predict_epoch_end(self) -> Optional[_PREDICT_OUTPUT]:
        """Calls ``on_predict_epoch_end`` hook.

        Returns:
            the results for all dataloaders
        """
        self.trainer._call_callback_hooks("on_predict_epoch_end")
        self.trainer._call_lightning_module_hook("on_predict_epoch_end")

        if self.return_predictions:
            return self.predictions

    def _on_predict_end(self) -> None:
        """Resets previous gradient status and calls ``on_predict_end`` hook."""
        if not self.return_predictions:
            self._predictions = []
        self.epoch_batch_indices = []

        # hook
        self.trainer._call_callback_hooks("on_predict_end")
        self.trainer._call_lightning_module_hook("on_predict_end")
        self.trainer._call_strategy_hook("on_predict_end")
