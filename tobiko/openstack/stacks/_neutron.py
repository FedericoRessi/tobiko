# Copyright (c) 2019 Red Hat, Inc.
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
from __future__ import absolute_import

import json

import netaddr
from oslo_log import log

import tobiko
from tobiko import config
from tobiko.openstack import heat
from tobiko.openstack import neutron
from tobiko.openstack.stacks import _hot


LOG = log.getLogger(__name__)


CONF = config.CONF
LOG = log.getLogger(__name__)


class FloatingNetworkStackFixture(heat.HeatStackFixture):

    template = _hot.heat_template_file('neutron/floating_network.yaml')

    @property
    def external_name(self):
        return tobiko.tobiko_config().neutron.floating_network

    _external_network = None

    @property
    def external_network(self):
        network = self._external_network
        if network is None:
            self._external_network = network = find_external_network(
                name=self.external_name) or {}
        return network

    @property
    def external_id(self):
        network = self.external_network
        return network and network['id'] or None

    @property
    def has_external_id(self):
        return bool(self.external_id)

    @property
    def network_details(self):
        return neutron.get_network(self.network_id)


@neutron.skip_if_missing_networking_extensions('port-security')
class NetworkStackFixture(heat.HeatStackFixture):
    """Heat stack for creating internal network with a router to external"""

    #: Heat template file
    template = _hot.heat_template_file('neutron/network.yaml')

    #: Disable port security by default for new network ports
    port_security_enabled = False

    @property
    def has_ipv4(self):
        """Whenever to setup IPv4 subnet"""
        return bool(CONF.tobiko.neutron.ipv4_cidr)

    @property
    def ipv4_cidr(self):
        if self.has_ipv4:
            return neutron.new_ipv4_cidr(seed=self.fixture_name)
        else:
            return None

    @property
    def has_ipv6(self):
        """Whenever to setup IPv6 subnet"""
        return bool(CONF.tobiko.neutron.ipv4_cidr)

    @property
    def ipv6_cidr(self):
        if self.has_ipv6:
            return neutron.new_ipv6_cidr(seed=self.fixture_name)
        else:
            return None

    @property
    def network_value_specs(self):
        """Extra network creation parameters"""
        return {}

    floating_network_stack = tobiko.required_setup_fixture(
        FloatingNetworkStackFixture)

    @property
    def floating_network(self):
        """Network ID where the Neutron floating IPs are created"""
        return self.floating_network_stack.network_id

    @property
    def gateway_network(self):
        """Network ID where gateway routes packages to"""
        return self.floating_network

    ha = False

    @property
    def gateway_value_specs(self):
        value_specs = {}
        if self.has_l3_ha:
            value_specs.update(ha=(self.ha or False))
        return value_specs

    @property
    def has_gateway(self):
        """Whenever to setup gateway router"""
        return bool(self.gateway_network)

    @property
    def has_net_mtu(self):
        """Whenever can obtain network MTU value"""
        return neutron.has_networking_extensions('net-mtu')

    @property
    def has_l3_ha(self):
        """Whenever can obtain gateway router HA value"""
        return neutron.has_networking_extensions('l3-ha')

    @property
    def network_details(self):
        return neutron.get_network(self.network_id)

    @property
    def ipv4_subnet_details(self):
        return neutron.get_subnet(self.ipv4_subnet_id)

    @property
    def ipv4_subnet_cidr(self):
        return netaddr.IPNetwork(self.ipv4_subnet_details['cidr'])

    @property
    def ipv4_subnet_gateway_ip(self):
        return netaddr.IPAddress(self.ipv4_subnet_details['gateway_ip'])

    @property
    def ipv6_subnet_details(self):
        return neutron.get_subnet(self.ipv6_subnet_id)

    @property
    def ipv6_subnet_cidr(self):
        return netaddr.IPNetwork(self.ipv6_subnet_details['cidr'])

    @property
    def ipv6_subnet_gateway_ip(self):
        return netaddr.IPAddress(self.ipv6_subnet_details['gateway_ip'])

    @property
    def gateway_details(self):
        return neutron.get_router(self.gateway_id)

    @property
    def external_gateway_ips(self):
        fixed_ips = self.gateway_details['external_gateway_info'][
            'external_fixed_ips']
        return tobiko.select(netaddr.IPAddress(fixed_ip['ip_address'])
                             for fixed_ip in fixed_ips)

    @property
    def ipv4_gateway_ports(self):
        return neutron.list_ports(fixed_ips='subnet_id=' + self.ipv4_subnet_id,
                                  device_id=self.gateway_id,
                                  network_id=self.network_id)

    @property
    def ipv6_gateway_ports(self):
        return neutron.list_ports(fixed_ips='subnet_id=' + self.ipv6_subnet_id,
                                  device_id=self.gateway_id,
                                  network_id=self.network_id)

    @property
    def external_geteway_ports(self):
        return neutron.list_ports(device_id=self.gateway_id,
                                  network_id=self.gateway_network_id)

    @property
    def ipv4_gateway_addresses(self):
        ips = tobiko.Selection()
        for port in self.ipv4_gateway_ports:
            ips.extend(neutron.list_port_ip_addresses(port))
        return ips

    @property
    def ipv6_gateway_addresses(self):
        ips = tobiko.Selection()
        for port in self.ipv6_gateway_ports:
            ips.extend(neutron.list_port_ip_addresses(port))
        return ips

    @property
    def external_gateway_addresses(self):
        ips = tobiko.Selection()
        for port in self.external_geteway_ports:
            ips.extend(neutron.list_port_ip_addresses(port))
        return ips

    @property
    def gateway_network_details(self):
        return neutron.get_network(self.gateway_network_id)


@neutron.skip_if_missing_networking_extensions('net-mtu-writable')
class NetworkWithNetMtuWriteStackFixture(NetworkStackFixture):

    @property
    def custom_mtu_size(self):
        return CONF.tobiko.neutron.custom_mtu_size

    @property
    def network_value_specs(self):
        value_specs = super(NetworkWithNetMtuWriteStackFixture,
                            self).network_value_specs
        return dict(value_specs, mtu=self.custom_mtu_size)


@neutron.skip_if_missing_networking_extensions('security-group')
class SecurityGroupsFixture(heat.HeatStackFixture):
    """Heat stack with some security groups

    """
    #: Heat template file
    template = _hot.heat_template_file('neutron/security_groups.yaml')


def find_external_network(name=None):
    network = None
    if name:
        try:
            network = neutron.get_network(name)
        except neutron.NoSuchNetwork:
            LOG.debug('No such network with ID %r', name)

    if not network:
        params = {'router:external': True, "status": "ACTIVE"}
        if name:
            params['name'] = name
        try:
            network = neutron.find_network(**params)
        except tobiko.ObjectNotFound:
            LOG.exception('No such network (%s):',
                          json.dumps(params, sort_keys=True))
            if name:
                message = ('No such external network with name or ID '
                           '{!r}').format(name)
                raise ValueError(message)

    if network:
        LOG.debug('Found external network %r:\n%s',
                  network['name'], json.dumps(network, indent=4,
                                              sort_keys=True))
    return network


def get_floating_network_id():
    return tobiko.setup_fixture(FloatingNetworkStackFixture).network_id


def get_floating_network():
    return tobiko.setup_fixture(FloatingNetworkStackFixture).network_details


def has_floating_network():
    return tobiko.setup_fixture(FloatingNetworkStackFixture).has_network


skip_if_missing_floating_network = tobiko.skip_unless(
    'Floating network not found', has_floating_network)
