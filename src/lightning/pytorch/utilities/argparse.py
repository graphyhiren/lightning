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
"""Utilities for Argument Parsing within Lightning Components."""

import inspect
import os
from argparse import _ArgumentGroup, Namespace
from ast import literal_eval
from contextlib import suppress
from functools import wraps
from typing import Any, Callable, cast, List, Tuple, Type, TypeVar, Union


_T = TypeVar("_T", bound=Callable[..., Any])
_ARGPARSE_CLS = Union[Type["pl.LightningDataModule"], Type["pl.Trainer"]]


def parse_env_variables(cls: _ARGPARSE_CLS, template: str = "PL_%(cls_name)s_%(cls_argument)s") -> Namespace:
    """Parse environment arguments if they are defined.

    Examples:

        >>> from lightning.pytorch import Trainer
        >>> parse_env_variables(Trainer)
        Namespace()
        >>> import os
        >>> os.environ["PL_TRAINER_DEVICES"] = '42'
        >>> os.environ["PL_TRAINER_BLABLABLA"] = '1.23'
        >>> parse_env_variables(Trainer)
        Namespace(devices=42)
        >>> del os.environ["PL_TRAINER_DEVICES"]
    """
    cls_arg_defaults = get_init_arguments_and_types(cls)

    env_args = {}
    for arg_name, _, _ in cls_arg_defaults:
        env = template % {"cls_name": cls.__name__.upper(), "cls_argument": arg_name.upper()}
        val = os.environ.get(env)
        if not (val is None or val == ""):
            # todo: specify the possible exception
            with suppress(Exception):
                # converting to native types like int/float/bool
                val = literal_eval(val)
            env_args[arg_name] = val
    return Namespace(**env_args)


def get_init_arguments_and_types(cls: _ARGPARSE_CLS) -> List[Tuple[str, Tuple, Any]]:
    r"""Scans the class signature and returns argument names, types and default values.

    Returns:
        List with tuples of 3 values:
        (argument name, set with argument types, argument default value).

    Examples:

        >>> from lightning.pytorch import Trainer
        >>> args = get_init_arguments_and_types(Trainer)

    """
    cls_default_params = inspect.signature(cls).parameters
    name_type_default = []
    for arg in cls_default_params:
        arg_type = cls_default_params[arg].annotation
        arg_default = cls_default_params[arg].default
        try:
            if type(arg_type).__name__ == "_LiteralGenericAlias":
                # Special case: Literal[a, b, c, ...]
                arg_types = tuple({type(a) for a in arg_type.__args__})
            elif "typing.Literal" in str(arg_type) or "typing_extensions.Literal" in str(arg_type):
                # Special case: Union[Literal, ...]
                arg_types = tuple({type(a) for union_args in arg_type.__args__ for a in union_args.__args__})
            else:
                # Special case: ComposedType[type0, type1, ...]
                arg_types = tuple(arg_type.__args__)
        except (AttributeError, TypeError):
            arg_types = (arg_type,)

        name_type_default.append((arg, arg_types, arg_default))

    return name_type_default


def _defaults_from_env_vars(fn: _T) -> _T:
    @wraps(fn)
    def insert_env_defaults(self: Any, *args: Any, **kwargs: Any) -> Any:
        cls = self.__class__  # get the class
        if args:  # in case any args passed move them to kwargs
            # parse only the argument names
            cls_arg_names = [arg[0] for arg in get_init_arguments_and_types(cls)]
            # convert args to kwargs
            kwargs.update(dict(zip(cls_arg_names, args)))
        env_variables = vars(parse_env_variables(cls))
        # update the kwargs by env variables
        kwargs = dict(list(env_variables.items()) + list(kwargs.items()))

        # all args were already moved to kwargs
        return fn(self, **kwargs)

    return cast(_T, insert_env_defaults)
