# Copyright (c) 2022 Red Hat, Inc.
#
# All Rights Reserved.
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
import os

import testtools

from tobiko import tripleo


PLAYBOOK_DIRNAME = os.path.join(os.path.dirname(__file__), 'playbooks')


@tripleo.skip_if_missing_undercloud
class OpenShiftTest(testtools.TestCase):

    @tripleo.skip_if_missing_tripleo_ansible_inventory
    def test_ping_all_hosts(self):
        tripleo.run_playbook_from_undercloud(
            playbook='ping-shiftstack.yaml',
            playbook_dirname=PLAYBOOK_DIRNAME)

    def test_debug_vars(self):
        tripleo.run_playbook_from_undercloud(
            playbook='debug-vars.yaml',
            playbook_dirname=PLAYBOOK_DIRNAME,
            vars_files=['vars/some-vars.yaml'])