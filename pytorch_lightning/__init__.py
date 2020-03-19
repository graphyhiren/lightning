"""Root package info."""

__version__ = '0.7.2-dev'
__author__ = 'William Falcon et al.'
__author_email__ = 'waf2107@columbia.edu'
__license__ = 'Apache-2.0'
__copyright__ = 'Copyright (c) 2018-2020, %s.' % __author__
__homepage__ = 'https://github.com/PyTorchLightning/pytorch-lightning'
# this has to be simple string, see: https://github.com/pypa/twine/issues/522
__docs__ = "PyTorch Lightning is the lightweight PyTorch wrapper for ML researchers." \
           " Scale your models. Write less boilerplate."

from logging import getLogger

_logger = getLogger("lightning")

try:
    # This variable is injected in the __builtins__ by the build
    # process. It used to enable importing subpackages of skimage when
    # the binaries are not built
    __LIGHTNING_SETUP__
except NameError:
    __LIGHTNING_SETUP__ = False

if __LIGHTNING_SETUP__:
    import sys  # pragma: no-cover
    sys.stderr.write('Partial import of `torchlightning` during the build process.\n')  # pragma: no-cover
    # We are not importing the rest of the lightning during the build process, as it may not be compiled yet
else:
    from pytorch_lightning.core import LightningModule
    from pytorch_lightning.trainer import Trainer
    from pytorch_lightning.callbacks import Callback
    from pytorch_lightning.core import data_loader

    __all__ = [
        'Trainer',
        'LightningModule',
        'Callback',
        'data_loader'
    ]
    # __call__ = __all__
