from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Union


class CheckpointIOPlugin(ABC):
    @abstractmethod
    def save_checkpoint(self, checkpoint: Dict[str, Any], filepath: Union[str, Path]) -> None:
        """Save model/training states as a checkpoint file through state-dump and file-write.

        Args:
            checkpoint: dict containing model and trainer state
            filepath: write-target file's path
        """

    @abstractmethod
    def load_checkpoint_file(self, checkpoint_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load checkpoint from a path when resuming or loading ckpt for test/validate/predict stages.
        Args:
            checkpoint_path: Path to checkpoint

        Returns: The loaded checkpoint.
        """
