import hashlib
import logging
import os
import signal
from copy import deepcopy
from enum import Enum
from multiprocessing import Process, Queue
from pathlib import Path
from threading import Thread
from time import sleep, time
from typing import Any, Callable, List, Literal, Optional
from urllib import parse

import boto3
from tqdm import tqdm

from lightning.data.cache import Cache
from lightning.data.cache.constants import _TORCH_2_1_0_AVAILABLE

if _TORCH_2_1_0_AVAILABLE:
    from torch.utils._pytree import tree_flatten, tree_unflatten

logger = logging.Logger(__name__)


def _download_data_target(root: str, remote_root: str, cache_dir: str, queue_in: Queue, queue_out: Queue) -> None:
    """This function is used to download data from a remote directory to a cache directory."""
    s3 = boto3.client("s3")
    while True:
        r = queue_in.get()

        if r is None:
            queue_out.put(None)
            return

        index, paths = r

        # Check whether all the files are already downloaded
        if all(os.path.exists(p.replace(root, cache_dir)) for p in paths):
            queue_out.put(index)
            continue

        # Download all the required paths to unblock the current index
        for path in paths:
            remote_path = path.replace(root, remote_root)
            obj = parse.urlparse(remote_path)

            if obj.scheme != "s3":
                raise ValueError(f"Expected obj.scheme to be `s3`, instead, got {obj.scheme} for remote={remote_path}")

            local_path = path.replace(root, cache_dir)

            dirpath = os.path.dirname(local_path)

            os.makedirs(dirpath, exist_ok=True)

            with open(local_path, "wb") as f:
                s3.download_fileobj(obj.netloc, obj.path.lstrip("/"), f)

        queue_out.put(index)


def _remove_target(root: str, cache_dir: str, queue_in: Queue) -> None:
    while True:
        paths = queue_in.get()

        if paths is None:
            return

        for path in paths:
            cached_filepath = path.replace(root, cache_dir)

            if os.path.exists(cached_filepath):
                os.remove(cached_filepath)


class BaseWorker:
    def __init__(
        self,
        index: int,
        start_index: int,
        node_rank: int,
        prepare_item: Callable,
        root: str,
        remote_root: str,
        items: List[Any],
        worker_queue: Queue,
        num_downloaders: int,
        remove: bool,
        chunk_size: Optional[int] = None,
        chunk_bytes: Optional[int] = None,
        compression: Optional[str] = None,
    ):
        """The BaseWorker is responsible to process the user data."""
        self.index = index
        self.start_index = start_index
        self.node_rank = node_rank
        self.prepare_item = prepare_item
        self.root = root
        self.remote_root = remote_root
        self.items = items
        self.num_downloaders = num_downloaders
        self.remove = remove
        self.chunk_bytes = chunk_bytes
        self.chunk_size = chunk_size
        self.compression = compression
        self._paths = []
        self._remover = None
        self._downloaders = []
        self._to_download_queues = []
        self._download_is_ready_queue = Queue()
        self._remove_queue = Queue()
        self._collected_items = 0
        self._counter = 0
        self._worker_queue = worker_queue

    def run(self):
        self._create_cache()
        self._collect_paths()
        self._start_downloaders()
        self._start_remover()

        is_none = 0
        while True:
            r = self._download_is_ready_queue.get()
            if r is None:
                is_none += 1
                if is_none == self.num_downloaders:
                    self._remove_queue.put(None)
                    self.cache.done()
                    return
                continue

            self.cache[r + self.start_index] = self.prepare_item(self.items[r]) if self.prepare_item else self.items[r]

            self._counter += 1

            if self._worker_queue:
                self._worker_queue.put((self.index, self._counter))

            if self.remove:
                self._remove_queue.put(self._paths[r])

    def _create_cache(self):
        algo = hashlib.new("sha256")
        algo.update(self.root.encode("utf-8"))
        root_hash = algo.hexdigest()

        cache_dir = f"/cache/{root_hash}/w_{self.node_rank}_{self.index}"
        os.makedirs(cache_dir, exist_ok=True)

        self.cache = Cache(
            cache_dir, chunk_bytes=self.chunk_bytes, chunk_size=self.chunk_size, compression=self.compression
        )

        self.cache_dir = f"/cache/{root_hash}/data"
        os.makedirs(self.cache_dir, exist_ok=True)

    def _collect_paths(self):
        items = []
        for item in self.items:
            flattened_item, spec = tree_flatten(item)

            # For speed reasons, we assume starting with `self.root` is enough to be a real file.
            # Other alternative would be too slow.
            # TODO: Try using dictionary for higher accurary.
            indexed_paths = {
                index: element
                for index, element in enumerate(flattened_item)
                if isinstance(element, str) and element.startswith(self.root)  # For speed reasons
            }

            if len(indexed_paths) == 0:
                raise ValueError(f"The provided item {item} didn't contain any filepaths.")

            paths = []
            for index, path in indexed_paths.items():
                tmp_path = path.replace(self.root, self.cache_dir)
                flattened_item[index] = tmp_path
                paths.append(path)

            self._paths.append(paths)

            items.append(tree_unflatten(flattened_item, spec))

            self._collected_items += 1

        self.items = items

    def _start_downloaders(self):
        for _ in range(self.num_downloaders):
            to_download_queue = Queue()
            p = Process(
                target=_download_data_target,
                args=(self.root, self.remote_root, self.cache_dir, to_download_queue, self._download_is_ready_queue),
            )
            p.start()
            self._downloaders.append(p)
            self._to_download_queues.append(to_download_queue)

        for index, paths in enumerate(self._paths):
            self._to_download_queues[index % self.num_downloaders].put((index, paths))

        for downloader_index in range(self.num_downloaders):
            self._to_download_queues[downloader_index].put(None)

    def _start_remover(self):
        if self.remove:
            self._remover = Process(
                target=_remove_target,
                args=(
                    self.root,
                    self.cache_dir,
                    self._remove_queue,
                ),
            )
            self._remover.start()


class DataWorkerThread(BaseWorker, Thread):
    def __init__(self, *args, **kwargs):
        """The DataWorkerThread is responsible to process the user data."""
        BaseWorker.__init__(self, *args, **kwargs)
        Thread.__init__(self, daemon=True)

    def join(self, timeout=None):
        for w in self._downloaders:
            w.kill()

        if self._remover is not None:
            self._remover.kill()

        super().join(timeout)

    def __len__(self):
        return self._counter

    @property
    def collected_items(self):
        return self._collected_items


class DataWorkerProcess(BaseWorker, Process):
    def __init__(self, *args, **kwargs):
        """The DataWorkerProcess is responsible to process the user data inside processes."""
        BaseWorker.__init__(self, *args, **kwargs)
        Process.__init__(self)


class WorkerType(Enum):
    THREAD = "thread"
    PROCESS = "process"


class DataProcessor:
    def __init__(
        self,
        setup: Callable[[str, str], List[str]],
        prepare_item: Optional[Callable] = None,
        num_workers: int = os.cpu_count() * 4,
        num_downloaders: int = 2,
        chunk_size: Optional[int] = None,
        chunk_bytes: Optional[int] = 1 << 26,
        compression: Optional[str] = None,
        delete_cached_files: bool = True,
        resolver: Optional[Callable[[str], str]] = None,
        worker_type: Literal["thread", "process"] = "process",
    ):
        """The `DataProcessor` provides an efficient way to process data across multiple nodes in the cloud into
        chunks.

        Arguments:
            setup: The function used to organize the dataset metadata.
            prepare_item: The function to used to prepare a single item from its metadata, including filepaths.
            num_workers: The number of worker threads to use.
            num_downloaders: The number of file downloaders to use.
            chunk_size: The maximum number of elements to store within a chunk.
            chunk_bytes: The maximum number of bytes to store within a chunk.
            compression: The compression algorithm to apply on over the chunks.
            delete_cached_files: Whether to delete the cached files.

        """
        self.setup = setup
        self.prepare_item = prepare_item
        self.num_workers = num_workers
        self.num_downloaders = num_downloaders
        self.chunk_size = chunk_size
        self.chunk_bytes = chunk_bytes
        self.delete_cached_files = delete_cached_files
        self.compression = compression
        self.workers = []
        self.resolver = resolver
        self.worker_type = worker_type
        self.workers_tracker = {}
        self.worker_queue = None

    def run(self, root: str, remote_root: Optional[str] = None) -> None:
        t0 = time()
        logger.info("Setup started")

        # Get the filepaths
        root = str(Path(root).resolve())
        filepaths = self._cached_list_filepaths(root)
        num_filepaths = len(filepaths)

        # Call the setup method of the user
        user_items = self.setup(root, filepaths)

        # Associate the items to the workers based on world_size and node_rank
        begins, workers_user_items = self._associated_items_to_workers(user_items)
        logger.info(f"Setup finished in {round(time() - t0, 3)} seconds. Found {num_filepaths} items to process.")

        logger.info(f"Starting {self.num_workers} workers")

        if remote_root is None and self.resolver is not None:
            remote_root = self.resolver(root)

        signal.signal(signal.SIGINT, self._signal_handler)

        if self.worker_type == WorkerType.THREAD.value:
            self._create_thread_workers(root, remote_root, user_items, begins, workers_user_items)
        else:
            self._create_process_workers(root, remote_root, begins, workers_user_items)

        logger.info("Workers are ready ! Starting data processing...")

        num_items = sum([len(items) for items in workers_user_items])

        if self.worker_type == WorkerType.THREAD.value:
            current_total = 0
            with tqdm(total=num_items, smoothing=0) as pbar:
                while True:
                    new_total = sum([len(w) for w in self.workers])
                    pbar.update(new_total - current_total)
                    current_total = new_total
                    sleep(1)
                    if current_total == num_items:
                        break
        else:
            current_total = 0
            with tqdm(total=num_items, smoothing=0) as pbar:
                while True:
                    index, counter = self.worker_queue.get()
                    self.workers_tracker[index] = counter
                    new_total = sum(self.workers_tracker.values())
                    pbar.update(new_total - current_total)
                    current_total = new_total
                    if current_total == num_items:
                        break

        for w in self.workers:
            if self.worker_type == WorkerType.THREAD.value:
                w.join(0)
            else:
                w.kill()

        logger.info("Finished data processing!")

    def _create_thread_workers(self, root, remote_root, user_items, begins, workers_user_items):
        num_items = len(user_items)
        current_total = 0
        with tqdm(total=num_items, smoothing=0) as pbar:
            for worker_idx, worker_user_items in enumerate(workers_user_items):
                new_total = sum([w.collected_items for w in self.workers])
                pbar.update(new_total - current_total)
                current_total = new_total
                worker = DataWorkerThread(
                    worker_idx,
                    begins[worker_idx],
                    self._get_node_rank(),
                    deepcopy(self.prepare_item),
                    root,
                    remote_root,
                    worker_user_items.tolist(),
                    None,
                    self.num_downloaders,
                    self.delete_cached_files,
                    self.chunk_size,
                    self.chunk_bytes,
                    self.compression,
                )
                worker.start()
                self.workers.append(worker)

            while True:
                new_total = sum([w.collected_items for w in self.workers])
                pbar.update(new_total - current_total)
                current_total = new_total
                sleep(1)
                if current_total == num_items:
                    break

    def _create_process_workers(self, root, remote_root, begins, workers_user_items):
        self.worker_queue = Queue()
        for worker_idx, worker_user_items in enumerate(workers_user_items):
            worker = DataWorkerProcess(
                worker_idx,
                begins[worker_idx],
                self._get_node_rank(),
                deepcopy(self.prepare_item),
                root,
                remote_root,
                worker_user_items.tolist(),
                self.worker_queue,
                self.num_downloaders,
                self.delete_cached_files,
                self.chunk_size,
                self.chunk_bytes,
                self.compression,
            )
            worker.start()
            self.workers.append(worker)

    def _associated_items_to_workers(self, user_items: List[Any]):
        # Associate the items to the workers based on world_size and node_rank
        num_nodes = self._get_num_nodes()
        current_node_rank = self._get_node_rank()
        node_size = len(user_items) // num_nodes
        workers_user_items = []
        begins = []
        for node_rank in range(num_nodes):
            if node_rank != current_node_rank:
                continue
            is_last_node = node_rank == num_nodes - 1
            start_node = node_rank * node_size
            end_node = len(user_items) if is_last_node else (node_rank + 1) * node_size
            node_user_items = user_items[start_node:end_node]
            worker_size = len(node_user_items) // self.num_workers
            for worker_idx in range(self.num_workers):
                is_last = worker_idx == self.num_workers - 1
                begin = worker_idx * worker_size
                end = len(node_user_items) if is_last else (worker_idx + 1) * worker_size
                workers_user_items.append(user_items[begin:end])
                begins.append(begin)
            return begins, workers_user_items

    def _cached_list_filepaths(self, root: str) -> List[str]:
        algo = hashlib.new("sha256")
        algo.update(root.encode("utf-8"))
        root_hash = algo.hexdigest()

        filepath = f"/cache/{root_hash}/filepaths.txt"

        if os.path.exists(filepath):
            lines = []
            with open(filepath) as f:
                for line in f.readlines():
                    lines.append(line.replace("\n", ""))
            return lines

        filepaths = []
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                filepaths.append(os.path.join(dirpath, filename))

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, "w") as f:
            for filepath in filepaths:
                f.write(f"{filepath}\n")

        return filepaths

    def _signal_handler(self, signal, frame):
        for w in self.workers:
            if self.worker_type == WorkerType.THREAD.value:
                w.join(0)
            else:
                w.kill()
        os._exit(0)

    def _get_num_nodes(self) -> int:
        return int(os.getenv("NUM_NODES", 1))

    def _get_node_rank(self) -> int:
        return int(os.getenv("NODE_RANK", 0))
