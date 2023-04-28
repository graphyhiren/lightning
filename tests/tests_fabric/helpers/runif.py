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
import pytest

from lightning.fabric.utilities.testing import _RunIf


def RunIf(**kwargs):
    reasons, marker_kwargs = _RunIf(**kwargs)
    return pytest.mark.skipif(condition=any(reasons), reason=f"Requires: [{' + '.join(reasons)}]", **marker_kwargs)
