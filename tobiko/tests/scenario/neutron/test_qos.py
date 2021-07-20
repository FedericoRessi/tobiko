# Copyright (c) 2021 Red Hat
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
from __future__ import absolute_import

from oslo_log import log
import testtools

import tobiko
from tobiko.openstack import keystone
from tobiko.openstack import stacks
from tobiko.openstack import neutron
from tobiko.shell import iperf
from tobiko.shell import ping


LOG = log.getLogger(__name__)


@keystone.skip_unless_has_keystone_credentials()
@neutron.skip_if_is_old_ovn()
class QoSNetworkTest(testtools.TestCase):
    """Tests QoS basic functionality"""

    #: Resources stacks with QoS Policy and QoS Rules and Advanced server
    network = tobiko.required_setup_fixture(stacks.QosNetworkStackFixture)
    policy = tobiko.required_setup_fixture(stacks.QosPolicyStackFixture)
    server = tobiko.required_setup_fixture(stacks.QosServerStackFixture)

    def test_ping(self):
        ping.assert_reachable_hosts([self.server.floating_ip_address],)

    def test_network_qos_policy_id(self):
        """Verify network policy ID"""
        self.assertEqual(self.policy.qos_policy_id,
                         self.network.qos_policy_id)

    def test_server_qos_policy_id(self):
        """Verify server policy ID"""
        self.assertIsNone(self.server.port_details['qos_policy_id'])

    def test_qos_bw_limit(self):
        """Verify BW limit using the iperf3 tool"""
        iperf.assert_bw_limit(ssh_client=None,  # localhost will act as client
                              ssh_server=self.server.peer_ssh_client)
