from typing import Any, Dict, Iterator, List, Union

import torch
from torchmetrics import Metric

_METRIC = Union[Metric, torch.Tensor, int, float]
_STEP_OUTPUT = Union[torch.Tensor, Dict[str, Any]]
_EPOCH_OUTPUT = List[_STEP_OUTPUT]
_PARAMETERS = Iterator[torch.nn.Parameter]
