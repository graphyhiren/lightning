from pytorch_lightning.plugins.training_type.ddp import DDPStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.ddp2 import DDP2Strategy  # noqa: F401
from pytorch_lightning.plugins.training_type.ddp_spawn import DDPSpawnPlugin  # noqa: F401
from pytorch_lightning.plugins.training_type.deepspeed import DeepSpeedStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.dp import DataParallelStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.fully_sharded import DDPFullyShardedStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.horovod import HorovodStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.parallel import ParallelPlugin  # noqa: F401
from pytorch_lightning.plugins.training_type.sharded import DDPShardedStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.sharded_spawn import DDPSpawnShardedPlugin  # noqa: F401
from pytorch_lightning.plugins.training_type.single_device import SingleDeviceStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.single_tpu import SingleTPUStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.tpu_spawn import TPUSpawnStrategy  # noqa: F401
from pytorch_lightning.plugins.training_type.training_type_plugin import Strategy  # noqa: F401
