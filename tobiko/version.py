# Copyright 2019 Red Hat
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from __future__ import absolute_import

import sys

import pbr.version


version_info = pbr.version.VersionInfo('tobiko')

release = version_info.release_string()
version = version_info.version_string()


if __name__ == '__main__':
    message = ("release: {release}\n"
               "version: {version}\n").format(
                   release=release, version=version)
    sys.stdout.write(message)
