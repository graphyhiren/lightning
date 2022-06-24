#!/usr/bin/env python
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
import glob
import logging
import os
import re
from itertools import groupby
from typing import List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_PACKAGE_MAPPING = {"pytorch": "pytorch_lightning", "app": "lightning_app"}


def load_requirements(
    path_dir: str, file_name: str = "base.txt", comment_char: str = "#", unfreeze: bool = True
) -> List[str]:
    """Load requirements from a file.

    >>> path_req = os.path.join(_PROJECT_ROOT, "requirements")
    >>> load_requirements(path_req)  # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    ['numpy...', 'torch...', ...]
    """
    with open(os.path.join(path_dir, file_name)) as file:
        lines = [ln.strip() for ln in file.readlines()]
    reqs = []
    for ln in lines:
        # filer all comments
        comment = ""
        if comment_char in ln:
            comment = ln[ln.index(comment_char) :]
            ln = ln[: ln.index(comment_char)]
        req = ln.strip()
        # skip directly installed dependencies
        if not req or req.startswith("http") or "@http" in req:
            continue
        # remove version restrictions unless they are strict
        if unfreeze and "<" in req and "strict" not in comment:
            req = re.sub(r",? *<=? *[\d\.\*]+", "", req).strip()
        reqs.append(req)
    return reqs


def load_readme_description(path_dir: str, homepage: str, version: str) -> str:
    """Load readme as decribtion.

    >>> load_readme_description(_PROJECT_ROOT, "", "")  # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
    '<div align="center">...'
    """
    path_readme = os.path.join(path_dir, "README.md")
    text = open(path_readme, encoding="utf-8").read()

    # drop images from readme
    text = text.replace("![PT to PL](docs/source/_static/images/general/pl_quick_start_full_compressed.gif)", "")

    # https://github.com/Lightning-AI/lightning/raw/master/docs/source/_static/images/lightning_module/pt_to_pl.png
    github_source_url = os.path.join(homepage, "raw", version)
    # replace relative repository path to absolute link to the release
    #  do not replace all "docs" as in the readme we reger some other sources with particular path to docs
    text = text.replace("docs/source/_static/", f"{os.path.join(github_source_url, 'docs/source/_static/')}")

    # readthedocs badge
    text = text.replace("badge/?version=stable", f"badge/?version={version}")
    text = text.replace("pytorch-lightning.readthedocs.io/en/stable/", f"pytorch-lightning.readthedocs.io/en/{version}")
    # codecov badge
    text = text.replace("/branch/master/graph/badge.svg", f"/release/{version}/graph/badge.svg")
    # replace github badges for release ones
    text = text.replace("badge.svg?branch=master&event=push", f"badge.svg?tag={version}")
    # Azure...
    text = text.replace("?branchName=master", f"?branchName=refs%2Ftags%2F{version}")
    text = re.sub(r"\?definitionId=\d+&branchName=master", f"?definitionId=2&branchName=refs%2Ftags%2F{version}", text)

    skip_begin = r"<!-- following section will be skipped from PyPI description -->"
    skip_end = r"<!-- end skipping PyPI description -->"
    # todo: wrap content as commented description
    text = re.sub(rf"{skip_begin}.+?{skip_end}", "<!--  -->", text, flags=re.IGNORECASE + re.DOTALL)

    # # https://github.com/Borda/pytorch-lightning/releases/download/1.1.0a6/codecov_badge.png
    # github_release_url = os.path.join(homepage, "releases", "download", version)
    # # download badge and replace url with local file
    # text = _parse_for_badge(text, github_release_url)
    return text


def replace_with_imports(lines: List[str], import_path: str, kword: str = "class") -> List[str]:
    """Parse a file and replace implementtaions bodies of func or function.

    >>> py_file = os.path.join(_PROJECT_ROOT, "src", "pytorch_lightning", "loggers", "logger.py")
    >>> import_path = ".".join(["pytorch_lightning", "loggers", "logger"])
    >>> with open(py_file, encoding="utf-8") as fp:
    ...     lines = [ln.rstrip() for ln in fp.readlines()]
    >>> lines = replace_with_imports(lines, import_path, "class")
    >>> lines = replace_with_imports(lines, import_path, "def")
    """
    body = []
    tracking = False
    skip_offset = 0
    for i, ln in enumerate(lines):
        offset = len(ln) - len(ln.lstrip())
        # in case of mating the class args are multi-line
        if tracking and ln and offset <= skip_offset and not any(ln.lstrip().startswith(c) for c in ")]"):
            tracking = False
        if ln.lstrip().startswith(f"{kword} ") and not tracking:
            name = ln.replace(f"{kword} ", "").strip()
            idxs = [name.index(c) for c in ":(" if c in name]
            name = name[: min(idxs)]
            # skip private, TODO: consider skip even protected
            if not name.startswith("__"):
                body.append(f"from {import_path} import {name}  # noqa: F401")
            tracking = True
            skip_offset = offset
            continue
        if not tracking:
            body.append(ln)
    return body


def create_meta_package(src_folder: str, pkg_name: str = "pytorch_lightning", lit_name: str = "pytorch"):
    """Parse the real python package and for each module create a mirroe version with repalcing all function and
    class implementations by cross-imports to the true package.

    >>> create_meta_package(os.path.join(_PROJECT_ROOT, "src"))
    """
    package_dir = os.path.join(src_folder, pkg_name)
    # shutil.rmtree(os.path.join(src_folder, "lightning", lit_name))
    py_files = glob.glob(os.path.join(src_folder, pkg_name, "**", "*.py"), recursive=True)
    for py_file in py_files:
        local_path = py_file.replace(package_dir + os.path.sep, "")
        fname = os.path.basename(py_file)
        if "-" in fname:
            continue
        with open(py_file, encoding="utf-8") as fp:
            lines = [ln.rstrip() for ln in fp.readlines()]
        lines = list(map(lambda ln: ln[: ln.index("#")] if "#" in ln else ln, lines))
        import_path = pkg_name + "." + local_path.replace(".py", "").replace(os.path.sep, ".")

        if fname in ("__about__.py", "__version__.py"):
            body = lines

        elif fname in ("__init__.py", "__main__.py"):
            body = replace_with_imports(lines, import_path, "class")
            body = replace_with_imports(body, import_path, "def")
        else:
            if fname.startswith("_"):
                logging.warning(f"unsupported file: {local_path}")
                continue
            # ToDO: perform some smarter parsing - preserve Constants, lambdas, etc
            body = [ln for ln in lines if not ln.startswith("import ")]
            body = [ln for ln in body if not (ln.startswith("from ") and " import " in ln)]
            body = replace_with_imports([ln.rstrip() for ln in body], import_path, "class")
            body = replace_with_imports(body, import_path, "def")

        # todo: apply pre-commit formatting
        body = [ln for ln, _group in groupby(body)]
        new_file = os.path.join(src_folder, "lightning", lit_name, local_path)
        os.makedirs(os.path.dirname(new_file), exist_ok=True)
        with open(new_file, "w", encoding="utf-8") as fp:
            fp.writelines([ln + os.linesep for ln in body])
