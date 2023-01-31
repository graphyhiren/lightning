from pathlib import Path
import os
from typing import Callable, Optional
from fsspec import AbstractFileSystem
import shutil
import sys
from fsspec.implementations.local import LocalFileSystem
from lightning_app.storage.copier import _copy_files
from lightning_app.storage.path import _filesystem, _shared_storage_path


def _get_files(self, fs, src: Path, dst: Path, overwrite: bool):
    if fs.isdir(src):
        if isinstance(fs, LocalFileSystem):
            dst = dst.resolve()
            if fs.exists(dst):
                if overwrite:
                    fs.rm(str(dst), recursive=True)
                else:
                    raise FileExistsError(f"The file {dst} was found. Add get(..., overwrite=True) to replace it.")

            shutil.copytree(src, dst)
        else:
            glob = f"{str(src)}/**"
            fs.get(glob, str(dst.absolute()), recursive=False)
    else:
        fs.get(str(src), str(dst.absolute()), recursive=False)

class FileSystem:

    """This filesystem enables to easily move files from and to the shared storage"""

    def __init__(self):
        self._fs = _filesystem()
        self._root = str(_shared_storage_path())

    def _validate_path(self, src_path: str, dst_path: str) -> None:
        if not os.path.exists(os.path.join(self._root, src_path)):
            raise FileExistsError(f"The provided path {src_path} doesn't exists")

        if str(Path(dst_path).resolve()) == dst_path:
            raise RuntimeError(f"The destination path {dst_path} should be relative.")

    def put(
        self,
        src_path: str,
        dst_path: str,
        put_fn: Callable = _copy_files
    ) -> None:
        """This method enables to put a file to the shared storage in a blocking fashion.

        Arguments:
            src_path: The path to your files locally
            dst_path: The path to your files transfered in the shared storage.
            put_fn: The method to use to put files in the shared storage.
        """
        self._validate_path(src_path, dst_path)

        src = Path(src_path).resolve()
        dst = Path(os.path.join(self._root, dst_path)).resolve()

        return put_fn(src, dst, fs=self._fs)

    def get(
        self,
        src_path: str,
        dst_path: str,
        get_fn: Callable = _get_files
    ) -> None:
        """This method enables to get files from the shared storage in a blocking fashion.

        Arguments:
            src_path: The path to your files in the shared storage
            dst_path: The path to your files transfered locally
            get_fn: The method to use to put files in the shared storage.
        """
        self._validate_path(src_path, dst_path)

        src = Path(src_path).resolve()
        dst = Path(os.path.join(self._root, dst_path)).resolve()

        return get_fn(src, dst)

    def list(self, path: str):
        """This method enables to list files from the shared storage in a blocking fashion.

        Arguments:
            path: The path to files to list.
        """

        path = Path(os.path.join(self._root, path)).resolve()
        paths = []

        if not self._fs.exists(path):
            return paths

        # Invalidate cache before running ls in case new directories have been added
        # TODO: Re-evaluate this - may lead to performance issues
        self._fs.invalidate_cache()

        paths = self._fs.ls(path)
        out = []
        if not paths:
            return []
        for path in paths:
            path = str(path).replace(self._root + "/", "")
            if self._fs.isdir(path):
                out.extend(self.list(path))
            else:
                out.append(path)
        return sorted(out)

    def delete(self, path):
        delete_path = Path(os.path.join(self._root, path)).resolve()

        if self._fs.exists(str(delete_path)):
            if self._fs.isdir(str(delete_path)):
                self._fs.rmdir(str(delete_path))
            else:
                self._fs.rm(str(delete_path))
        else:
            raise Exception(f"The file path {path} doesn't exist.")