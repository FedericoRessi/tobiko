# Copyright 2021 Red Hat
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

import itertools

from oslo_config import cfg

GROUP_NAME = "iperf"
OPTIONS = [
    cfg.IntOpt('port',
               default=1234,
               help="Port number"),
    cfg.StrOpt('protocol',
               default='tcp',
               choices=['tcp', 'udp'],
               help="tcp and udp values are supported"),
    cfg.StrOpt('output_format',
               default='json',
               choices=['', 'json'],
               help="output format"),
    cfg.IntOpt('bitrate',
               default=20000000,
               help="target bit rate"),
    cfg.BoolOpt('download',
                default=True,
                help="direction download (True) or upload (False)"),
    cfg.IntOpt('timeout',
               default=10,
               help="timeout of the iperf test")]


def register_tobiko_options(conf):
    conf.register_opts(group=cfg.OptGroup(GROUP_NAME), opts=OPTIONS)


def list_options():
    return [(GROUP_NAME, itertools.chain(OPTIONS))]
