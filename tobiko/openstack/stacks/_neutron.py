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
import typing

import netaddr
from oslo_log import log

import tobiko
from tobiko import config
from tobiko.openstack import heat
from tobiko.openstack import neutron
from tobiko.openstack.stacks import _hot
from tobiko.shell import ip
from tobiko.shell import sh
from tobiko.shell import ssh


CONF = config.CONF
LOG = log.getLogger(__name__)


class ExternalNetworkStackFixture(heat.HeatStackFixture):

    template = _hot.heat_template_file('neutron/external_network.yaml')

    @property
    def external_name(self) -> typing.Optional[str]:
        return tobiko.tobiko_config().neutron.external_network

    subnet_enable_dhcp: typing.Optional[bool] = False

    _external_network: typing.Optional[neutron.NetworkType] = None

    @property
    def external_network(self) -> typing.Optional[neutron.NetworkType]:
        external_network = self._external_network
        if external_network is None:
            subnet_parameters: typing.Dict[str, typing.Any] = {}
            if self.subnet_enable_dhcp is not None:
                subnet_parameters['enable_dhcp'] = self.subnet_enable_dhcp
            for network in list_external_networks(name=self.external_name):
                if not network['subnets']:
                    LOG.debug(f"Network '{network['id']}' has any subnet")
                    continue
                subnets = neutron.list_subnets(network_id=network['id'],
                                               **subnet_parameters)
                if not subnets:
                    LOG.debug(f"Network '{network['id']}' has any valid "
                              f"subnet: {subnet_parameters}")
                    continue

                network_dump = json.dumps(network, indent=4, sort_keys=True)
                LOG.debug(f"Found external network for {self.fixture_name}:\n"
                          f"{network_dump}")

                subnets_dump = json.dumps(subnets, indent=4, sort_keys=True)
                LOG.debug(f"External subnets for {self.fixture_name}:\n"
                          f"{subnets_dump}")
                self._external_network = external_network = network
                break
            else:
                LOG.warning("No external network found for "
                            f"'{self.fixture_name}':\n"
                            f" - name or ID: {self.external_name}\n"
                            f" - subnet attributes: {subnet_parameters}\n")
        return external_network

    @property
    def external_id(self) -> typing.Optional[str]:
        network = self.external_network
        if network is None:
            return None
        else:
            return network['id']

    @property
    def has_external_id(self):
        return bool(self.external_network)

    @property
    def network_details(self) -> neutron.NetworkType:
        return neutron.get_network(self.network_id)

    @property
    def has_network(self) -> bool:
        return bool(self.network_id)

    has_gateway = False

    @property
    def create_router(self) -> bool:
        return False

    @property
    def has_l3_ha(self):
        """Whenever can obtain gateway router HA value"""
        return neutron.has_networking_extensions('l3-ha')

    ha = False

    @property
    def router_value_specs(self) -> typing.Dict[str, typing.Any]:
        value_specs: typing.Dict[str, typing.Any] = {}
        if self.has_l3_ha:
            value_specs.update(ha=bool(self.ha))
        return value_specs

    @property
    def has_router(self) -> bool:
        return bool(self.router_id)

    @property
    def router_details(self) -> neutron.RouterType:
        return neutron.get_router(self.router_id)


class RouterStackFixture(ExternalNetworkStackFixture):

    def __init__(self,
                 neutron_client: neutron.NeutronClientType = None):
        super(RouterStackFixture, self).__init__()
        self._neutron_client = neutron_client

    @property
    def external_name(self) -> typing.Optional[str]:
        return tobiko.tobiko_config().neutron.floating_network

    subnet_enable_dhcp = None

    @property
    def create_router(self) -> bool:
        return self.has_external_id

    @property
    def neutron_required_quota_set(self) -> typing.Dict[str, int]:
        requirements = super().neutron_required_quota_set
        if self.create_router:
            requirements['router'] += 1
        return requirements

    def ensure_router_interface(self,
                                subnet: neutron.SubnetIdType = None,
                                network: neutron.NetworkIdType = None):
        ensure_router_interface(network=network,
                                subnet=subnet,
                                router=self.router_id,
                                client=self.neutron_client)

    @property
    def neutron_client(self) -> neutron.NeutronClientType:
        if self._neutron_client is None:
            self._neutron_client = neutron.neutron_client()
        return self._neutron_client


def ensure_router_interface(
        router: neutron.RouterIdType = None,
        subnet: neutron.SubnetIdType = None,
        network: neutron.NetworkIdType = None,
        client: neutron.NeutronClientType = None,
        add_cleanup=False) -> neutron.PortType:
    client = neutron.neutron_client(client)
    if router is None:
        router = get_router_id()
    if subnet is None and network is None:
        raise ValueError('Must specify a network or a subnet')
    try:
        port = neutron.find_port(network=network,
                                 device=router,
                                 subnet=subnet,
                                 client=client)
    except tobiko.ObjectNotFound:
        pass
    else:
        port_dump = json.dumps(port, indent=4, sort_keys=True)
        LOG.debug(f'Router interface already exist:\n{port_dump}')
        return port

    if subnet is None:
        assert network is not None
        LOG.info("Add router interface to network "
                 f"{neutron.get_network_id(network)}")
        for _subnet in neutron.list_subnets(network=network,
                                            client=client):
            neutron.ensure_subnet_gateway(subnet=_subnet,
                                          client=client)
    else:
        subnet = neutron.ensure_subnet_gateway(subnet=subnet,
                                               client=client)
        gateway_ip = subnet['gateway_ip']
        try:
            port = neutron.find_port(fixed_ips=[f'ip_address={gateway_ip}'],
                                     client=client)
        except tobiko.ObjectNotFound:
            LOG.info("Add router interface to subnet "
                     f"{neutron.get_subnet_id(subnet)}")
        else:
            # it must force router to bind new network port because subnet
            # gateway IP address is already being used
            port_dump = json.dumps(port, indent=4, sort_keys=True)
            LOG.debug(f'Port with gateway IP already exists:\n{port_dump}')
            if network is None:
                network = subnet['network_id']
            subnet = None
            LOG.info("Add router interface to network "
                     f"{neutron.get_network_id(network)}")

    stack = RouterInterfaceStackFixture(router=router,
                                        subnet=subnet,
                                        network=network,
                                        neutron_client=client)
    if add_cleanup:
        tobiko.use_fixture(stack)
    else:
        tobiko.setup_fixture(stack)
    return stack.port_details


@neutron.skip_if_missing_networking_extensions('port-security')
class NetworkStackFixture(heat.HeatStackFixture):
    """Heat stack for creating internal network with a router to external"""

    #: Heat template file
    template = _hot.heat_template_file('neutron/network.yaml')

    #: Enable port security by default for new network ports
    port_security_enabled = True

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
        return bool(CONF.tobiko.neutron.ipv6_cidr)

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

    gateway_stack = tobiko.required_fixture(RouterStackFixture)

    @property
    def ha(self) -> bool:
        return self.gateway_stack.ha

    @property
    def floating_network(self):
        """Network ID where the Neutron floating IPs are created"""
        return self.gateway_stack.network_id

    @property
    def gateway_network(self):
        """Network ID where gateway routes packages to"""
        return self.floating_network

    @property
    def gateway(self) -> str:
        return self.gateway_stack.router_id

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
    def ipv4_dns_nameservers(self):
        nameservers = CONF.tobiko.neutron.ipv4_dns_nameservers
        if nameservers is None:
            nameservers = default_nameservers(ip_version=4)
        return ','.join(str(nameserver) for nameserver in nameservers)

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
    def ipv6_dns_nameservers(self):
        nameservers = CONF.tobiko.neutron.ipv6_dns_nameservers
        if nameservers is None:
            nameservers = default_nameservers(ip_version=6)
        return ','.join(str(nameserver) for nameserver in nameservers)

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

    @property
    def neutron_required_quota_set(self) -> typing.Dict[str, int]:
        requirements = super().neutron_required_quota_set
        requirements['network'] += 1
        if self.has_ipv4:
            requirements['subnet'] += 1
        if self.has_ipv6:
            requirements['subnet'] += 1
        return requirements

    def is_router_distributed(self) -> bool:
        if self.has_gateway:
            tobiko.setup_fixture(self)
            return bool(self.gateway_details.get('distributed'))
        else:
            return False

    @classmethod
    def skip_if_router_is_distributed(cls, reason: str = None):
        fixture = tobiko.get_fixture(cls)
        if reason is None:
            reason = "Distributed router is not supported"
        return tobiko.skip_if(reason=reason,
                              predicate=fixture.is_router_distributed)


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


def list_external_networks(name: str = None) -> \
        tobiko.Selection[neutron.NetworkType]:
    networks = tobiko.Selection[neutron.NetworkType]()
    if name is not None:
        try:
            network = neutron.get_network(name)
        except neutron.NoSuchNetwork:
            LOG.error(f"No such network with ID '{name}'")
        else:
            networks.append(network)
    if not networks:
        network_params = {'router:external': True, "status": "ACTIVE"}
        if name is not None:
            network_params['name'] = name
        networks += neutron.list_networks(**network_params)
    if not networks and name:
        raise ValueError("No such external network with name or ID "
                         f"'{name}'")
    return networks


def get_external_network_id():
    return tobiko.setup_fixture(ExternalNetworkStackFixture).network_id


def get_external_network():
    return tobiko.setup_fixture(ExternalNetworkStackFixture).network_details


def has_external_network():
    return tobiko.setup_fixture(ExternalNetworkStackFixture).has_network


skip_unless_has_external_network = tobiko.skip_unless(
    'External network not found', has_external_network)


def get_floating_network_id() -> str:
    return tobiko.setup_fixture(RouterStackFixture).network_id


def get_floating_network() -> neutron.NetworkType:
    return tobiko.setup_fixture(RouterStackFixture).network_details


def has_floating_network() -> bool:
    return tobiko.setup_fixture(RouterStackFixture).has_network


skip_unless_has_floating_network = tobiko.skip_unless(
    'Floating network not found', has_floating_network)


def get_router_id() -> str:
    return tobiko.setup_fixture(RouterStackFixture).router_id


def get_router() -> neutron.RouterType:
    return tobiko.setup_fixture(RouterStackFixture).router_details


def has_router() -> bool:
    return tobiko.setup_fixture(RouterStackFixture).has_router


skip_unless_has_router = tobiko.skip_unless(
    'External router not created', has_router)


class DefaultNameserversFixture(tobiko.SharedFixture):

    remove_local_ips = True
    max_count = 3
    ip_version = None

    nameservers: typing.Optional[tobiko.Selection[netaddr.IPAddress]] = None

    @property
    def ssh_client(self):
        host = tobiko.tobiko_config().neutron.nameservers_host
        if host is None:
            return ssh.ssh_proxy_client()
        else:
            return ssh.ssh_client(host)

    @property
    def filenames(self):
        return tuple(tobiko.tobiko_config().neutron.nameservers_filenames)

    def setup_fixture(self):
        self.nameservers = self.list_nameservers()

    def list_nameservers(self) -> tobiko.Selection[netaddr.IPAddress]:
        nameservers: tobiko.Selection[netaddr.IPAddress]
        if has_external_network():
            network_id = get_external_network_id()
            nameservers = neutron.list_network_nameservers(
                network_id=network_id)
            LOG.debug("Nameservers copied from external network: "
                      f"{nameservers}")
        else:
            # Copy nameservers from target host
            nameservers = sh.list_nameservers(ssh_client=self.ssh_client,
                                              ip_version=self.ip_version,
                                              filenames=self.filenames)
            if self.remove_local_ips:
                local_ips = ip.list_ip_addresses(scope='host')
                if local_ips:
                    # Filter out all local IPs
                    nameservers = tobiko.Selection[netaddr.IPAddress](
                        nameserver for nameserver in nameservers
                        if nameserver not in local_ips)
            LOG.debug(f"Nameservers copied from host: {nameservers}")
        if self.max_count:
            # Keep only up to max_count nameservers
            actual_count = len(nameservers)
            if actual_count > self.max_count:
                LOG.waring("Limit the number of nameservers from "
                           f"{actual_count} to {self.max_count}: "
                           f"{nameservers}")
                nameservers = tobiko.Selection[netaddr.IPAddress](
                    nameservers[:self.max_count])
        return nameservers


DEFAULT_NAMESERVERS_FIXTURE = DefaultNameserversFixture


def default_nameservers(
        ip_version: typing.Optional[int] = None) -> \
        tobiko.Selection[netaddr.IPAddress]:
    nameservers = tobiko.setup_fixture(
        DEFAULT_NAMESERVERS_FIXTURE).nameservers
    if ip_version is not None:
        nameservers = nameservers.with_attributes(version=ip_version)
    return nameservers


class FloatingIpStackFixture(heat.HeatStackFixture):

    #: Heat template file
    template = _hot.heat_template_file('neutron/floating_ip.yaml')

    router_stack = tobiko.required_fixture(RouterStackFixture)

    def __init__(self,
                 stack_name: str = None,
                 network: neutron.NetworkIdType = None,
                 port: neutron.PortIdType = None,
                 device_id: str = None,
                 fixed_ip_address: str = None,
                 neutron_client: neutron.NeutronClientType = None):
        self._network = network
        self._port = port
        self._neutron_client = neutron_client
        self._device_id = device_id
        self._fixed_ip_address = fixed_ip_address
        super(FloatingIpStackFixture, self).__init__(stack_name=stack_name)

    @property
    def network(self) -> str:
        network = self._network
        if network is None:
            return self.router_stack.network_id
        else:
            return neutron.get_network_id(network)

    @property
    def port(self) -> str:
        if isinstance(self._port, str):
            return self._port
        else:
            return self.port_details['id']

    @property
    def port_details(self) -> neutron.PortType:
        if self._port is None:
            params: typing.Dict[str, typing.Any] = {}
            device_id = self.device_id
            if device_id is not None:
                params['device_id'] = device_id
            self._port = neutron.find_port(
                client=self.neutron_client,
                fixed_ips=[f'ip_address={self.fixed_ip_address}'],
                **params)
        elif isinstance(self._port, str):
            self._port = neutron.get_port(self.port,
                                          client=self.neutron_client)
        assert isinstance(self._port, dict)
        return self._port

    @property
    def fixed_ip_address(self) -> str:
        if self._fixed_ip_address is None:
            raise ValueError(
                'Must specify at least a port or a fixed IP address')
        return self._fixed_ip_address

    @property
    def device_id(self) -> typing.Optional[str]:
        return self._device_id

    def setup_stack_name(self) -> str:
        stack_name = self.stack_name
        if stack_name is None:
            self.stack_name = stack_name = f"{self.fixture_name}-{self.port}"
        return stack_name

    def prepare_external_resources(self):
        super().prepare_external_resources()
        for fixed_ip in self.port_details['fixed_ips']:
            self.router_stack.ensure_router_interface(
                subnet=fixed_ip['subnet_id'])

    @property
    def network_details(self) -> neutron.NetworkType:
        return neutron.get_network(self.network_id)

    @property
    def router_details(self) -> neutron.RouterType:
        return neutron.get_router(self.router_id)

    @property
    def floating_ip_details(self) -> neutron.FloatingIpType:
        return neutron.get_floating_ip(self.floating_ip_id)

    @property
    def neutron_client(self) -> neutron.NeutronClientType:
        if self._neutron_client is None:
            self._neutron_client = self.router_stack.neutron_client
        return self._neutron_client


class RouterInterfaceStackFixture(heat.HeatStackFixture):

    #: Heat template file
    template = _hot.heat_template_file('neutron/router_interface.yaml')

    def __init__(self,
                 stack_name: str = None,
                 router: neutron.RouterIdType = None,
                 network: neutron.NetworkIdType = None,
                 subnet: neutron.SubnetIdType = None,
                 neutron_client: neutron.NeutronClientType = None):
        self._router = router
        self._network = network
        self._subnet = subnet
        self._neutron_client = neutron_client
        super().__init__(stack_name=stack_name)

    @property
    def router(self) -> str:
        if self._router is None:
            self._router = get_router_id()
        return neutron.get_router_id(self._router)

    @property
    def router_details(self) -> neutron.RouterType:
        if self._router is None or isinstance(self._router, str):
            self._router = neutron.get_router(self.router,
                                              client=self.neutron_client)
        return self._router

    @property
    def network(self) -> str:
        if self._network is None:
            subnet = self.subnet_details
            if subnet is None:
                raise ValueError('Must specify at least network or subnet')
            self._network = subnet['network_id']
        return neutron.get_network_id(self._network)

    @property
    def network_details(self) -> neutron.NetworkType:
        if self._network is None or isinstance(self._network, str):
            self._network = neutron.get_network(self.network,
                                                client=self.neutron_client)
        return self._network

    @property
    def subnet(self) -> typing.Optional[str]:
        if self._subnet is None:
            return None
        else:
            return neutron.get_subnet_id(self._subnet)

    @property
    def subnet_details(self) -> typing.Optional[neutron.SubnetType]:
        if self._subnet is None:
            return None
        if isinstance(self._subnet, str):
            self._subnet = neutron.get_subnet(self._subnet,
                                              client=self.neutron_client)
        return self._subnet

    @property
    def has_subnet(self) -> bool:
        return self.subnet is not None

    def setup_stack_name(self) -> str:
        if self.stack_name is None:
            if self.has_subnet:
                self.stack_name = f"{self.fixture_name}-{self.subnet}"
            else:
                self.stack_name = f"{self.fixture_name}-{self.network}"
        return self.stack_name

    _port: typing.Optional[neutron.PortIdType] = None

    @property
    def port_details(self) -> neutron.PortType:
        if self._port is None:
            port_id = self.port_id
            if port_id is None:
                self._port = neutron.find_port(network_id=self.network_id,
                                               device_id=self.router_id,
                                               client=self.neutron_client)
            else:
                self._port = neutron.get_port(port_id,
                                              client=self.neutron_client)
        assert isinstance(self._port, dict)
        return self._port

    @property
    def neutron_client(self) -> neutron.NeutronClientType:
        if self._neutron_client is None:
            self._neutron_client = neutron.get_neutron_client()
        return self._neutron_client
