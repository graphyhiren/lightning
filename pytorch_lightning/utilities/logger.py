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
"""Utilities for loggers."""

from argparse import Namespace
from typing import Any, Callable, Dict, MutableMapping, Union

import numpy as np
import torch


def _convert_params(params: Union[Dict[str, Any], Namespace]) -> Dict[str, Any]:
    # in case converting from namespace
    if isinstance(params, Namespace):
        params = vars(params)

    if params is None:
        params = {}

    return params


def _sanitize_callable_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize callable params dict, e.g. ``{'a': <function_**** at 0x****>} -> {'a': 'function_****'}``.

    Args:
        params: Dictionary containing the hyperparameters

    Returns:
        dictionary with all callables sanitized
    """

    def _sanitize_callable(val):
        # Give them one chance to return a value. Don't go rabbit hole of recursive call
        if isinstance(val, Callable):
            try:
                _val = val()
                if isinstance(_val, Callable):
                    return val.__name__
                return _val
            # todo: specify the possible exception
            except Exception:
                return getattr(val, "__name__", None)
        return val

    return {key: _sanitize_callable(val) for key, val in params.items()}


def _flatten_dict(params: Dict[Any, Any], delimiter: str = "/") -> Dict[str, Any]:
    """Flatten hierarchical dict, e.g. ``{'a': {'b': 'c'}} -> {'a/b': 'c'}``.

    Args:
        params: Dictionary containing the hyperparameters
        delimiter: Delimiter to express the hierarchy. Defaults to ``'/'``.

    Returns:
        Flattened dict.

    Examples:
        >>> _flatten_dict({'a': {'b': 'c'}})
        {'a/b': 'c'}
        >>> _flatten_dict({'a': {'b': 123}})
        {'a/b': 123}
        >>> _flatten_dict({5: {'a': 123}})
        {'5/a': 123}
    """

    def _dict_generator(input_dict, prefixes=None):
        prefixes = prefixes[:] if prefixes else []
        if isinstance(input_dict, MutableMapping):
            for key, value in input_dict.items():
                key = str(key)
                if isinstance(value, (MutableMapping, Namespace)):
                    value = vars(value) if isinstance(value, Namespace) else value
                    yield from _dict_generator(value, prefixes + [key])
                else:
                    yield prefixes + [key, value if value is not None else str(None)]
        else:
            yield prefixes + [input_dict if input_dict is None else str(input_dict)]

    return {delimiter.join(keys): val for *keys, val in _dict_generator(params)}


def _sanitize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Returns params with non-primitvies converted to strings for logging.

    >>> params = {"float": 0.3,
    ...           "int": 1,
    ...           "string": "abc",
    ...           "bool": True,
    ...           "list": [1, 2, 3],
    ...           "namespace": Namespace(foo=3),
    ...           "layer": torch.nn.BatchNorm1d}
    >>> import pprint
    >>> pprint.pprint(_sanitize_params(params))  # doctest: +NORMALIZE_WHITESPACE
    {'bool': True,
        'float': 0.3,
        'int': 1,
        'layer': "<class 'torch.nn.modules.batchnorm.BatchNorm1d'>",
        'list': '[1, 2, 3]',
        'namespace': 'Namespace(foo=3)',
        'string': 'abc'}
    """
    for k in params.keys():
        # convert relevant np scalars to python types first (instead of str)
        if isinstance(params[k], (np.bool_, np.integer, np.floating)):
            params[k] = params[k].item()
        elif type(params[k]) not in [bool, int, float, str, torch.Tensor]:
            params[k] = str(params[k])
    return params


def _add_prefix(metrics: Dict[str, float], prefix: str, logger_join_char: str):
    if prefix:
        metrics = {f"{prefix}{logger_join_char}{k}": v for k, v in metrics.items()}

    return metrics
