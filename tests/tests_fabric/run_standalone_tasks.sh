#!/bin/bash
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
set -e
# THIS FILE ASSUMES IT IS RUN INSIDE THE tests/tests_fabric DIRECTORY

# this environment variable allows special tests to run
export PL_RUN_STANDALONE_TESTS=1

echo "Run parity tests manually"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python parity/test_parity_ddp.py --accelerator "cpu" --devices 2
python parity/test_parity_ddp.py --accelerator "cuda" --devices 2
