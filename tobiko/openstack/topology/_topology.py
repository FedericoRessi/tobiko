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

import collections
import typing  # noqa
import weakref

import netaddr
from oslo_log import log
import six
from six.moves.urllib import parse

import tobiko
from tobiko import docker
from tobiko import podman
from tobiko.shell import ip
from tobiko.shell import sh
from tobiko.shell import ssh
from tobiko.openstack import neutron
from tobiko.openstack import nova
from tobiko.openstack import keystone
from tobiko.openstack.topology import _address
from tobiko.openstack.topology import _config
from tobiko.openstack.topology import _connection
from tobiko.openstack.topology import _exception


LOG = log.getLogger(__name__)


def list_openstack_nodes(topology=None, group=None, hostnames=None, **kwargs):
    topology = topology or get_openstack_topology()
    if group is None:
        nodes = topology.nodes
    elif isinstance(group, str):
        nodes = topology.get_group(group=group)
    else:
        nodes = topology.get_groups(groups=group)

    if hostnames:
        names = {node_name_from_hostname(hostname)
                 for hostname in hostnames}
        nodes = [node
                 for node in nodes
                 if node.name in names]
    if kwargs:
        nodes = nodes.with_attributes(**kwargs)
    return nodes


def find_openstack_node(topology=None, unique=False, **kwargs):
    nodes = list_openstack_nodes(topology=topology, **kwargs)
    if unique:
        return nodes.unique
    else:
        return nodes.first


def get_openstack_node(hostname, address=None, topology=None):
    topology = topology or get_openstack_topology()
    return topology.get_node(hostname=hostname, address=address)


def list_openstack_node_groups(topology=None):
    topology = topology or get_openstack_topology()
    return topology.groups


def get_default_openstack_topology_class() -> typing.Type:
    return DEFAULT_TOPOLOGY_CLASS


def set_default_openstack_topology_class(topology_class: typing.Type):
    # pylint: disable=global-statement
    if not issubclass(topology_class, OpenStackTopology):
        raise TypeError(f"'{topology_class}' is not subclass of "
                        f"'{OpenStackTopology}'")
    global DEFAULT_TOPOLOGY_CLASS
    DEFAULT_TOPOLOGY_CLASS = topology_class


def get_agent_service_name(agent_name: str) -> str:
    topology_class = get_default_openstack_topology_class()
    return topology_class.get_agent_service_name(agent_name)


class UnknowOpenStackServiceNameError(tobiko.TobikoException):
    message = ("Unknown service name for agent name '{agent_name}' and "
               "topology class '{topology_class}'")


class OpenStackTopologyNode(object):

    _docker_client = None
    _podman_client = None

    def __init__(self, topology, name: str, ssh_client: ssh.SSHClientFixture,
                 addresses: typing.List[netaddr.IPAddress], hostname: str):
        self._topology = weakref.ref(topology)
        self.name = name
        self.ssh_client = ssh_client
        self.groups: typing.Set[str] = set()
        self.addresses: typing.List[netaddr.IPAddress] = list(addresses)
        self.hostname: str = hostname

    @property
    def topology(self):
        return self._topology()

    def add_group(self, group: str):
        self.groups.add(group)

    @property
    def public_ip(self):
        return self.addresses[0]

    @property
    def ssh_parameters(self):
        return self.ssh_client.setup_connect_parameters()

    @property
    def docker_client(self):
        docker_client = self._docker_client
        if not docker_client:
            self._docker_client = docker_client = docker.get_docker_client(
                ssh_client=self.ssh_client)
        return docker_client

    @property
    def podman_client(self):
        podman_client = self._podman_client
        if not podman_client:
            self._podman_client = podman_client = podman.get_podman_client(
                ssh_client=self.ssh_client)
        return podman_client

    def __repr__(self):
        return "{cls!s}<name={name!r}>".format(cls=type(self).__name__,
                                               name=self.name)


class OpenStackTopology(tobiko.SharedFixture):

    config = tobiko.required_setup_fixture(_config.OpenStackTopologyConfig)

    agent_to_service_name_mappings = {
        neutron.DHCP_AGENT: 'devstack@q-dhcp',
        neutron.L3_AGENT: 'devstack@q-l3',
        neutron.OPENVSWITCH_AGENT: 'devstack@q-agt',
        neutron.METADATA_AGENT: 'devstack@q-meta'
    }

    has_containers = False

    _connections = tobiko.required_setup_fixture(
        _connection.SSHConnectionManager)

    def __init__(self):
        super(OpenStackTopology, self).__init__()
        self._names: typing.Dict[str, OpenStackTopologyNode] = (
            collections.OrderedDict())
        self._groups: typing.Dict[str, tobiko.Selection] = (
            collections.OrderedDict())
        self._addresses: typing.Dict[netaddr.IPAddress,
                                     OpenStackTopologyNode] = (
            collections.OrderedDict())

    def setup_fixture(self):
        self.discover_nodes()

    def cleanup_fixture(self):
        tobiko.cleanup_fixture(self._connections)
        self._names.clear()
        self._groups.clear()
        self._addresses.clear()

    @classmethod
    def get_agent_service_name(cls, agent_name: str) -> str:
        try:
            return cls.agent_to_service_name_mappings[agent_name]
        except KeyError:
            pass
        raise UnknowOpenStackServiceNameError(agent_name=agent_name,
                                              topology_class=cls)

    def discover_nodes(self):
        self.discover_configured_nodes()
        self.discover_controller_nodes()
        self.discover_compute_nodes()

    def discover_configured_nodes(self):
        for address in self.config.conf.nodes or []:
            self.add_node(address=address)

    def discover_controller_nodes(self):
        endpoints = keystone.list_endpoints(interface='public')
        addresses = set(parse.urlparse(endpoint.url).hostname
                        for endpoint in endpoints)
        for address in addresses:
            try:
                self.add_node(address=address, group='controller')
            except _connection.UreachableSSHServer as ex:
                LOG.debug(f"Unable to SSH to end point address '{address}'. "
                          f"{ex}")

    def discover_compute_nodes(self):
        for hypervisor in nova.list_hypervisors():
            self.add_node(hostname=hypervisor.hypervisor_hostname,
                          address=hypervisor.host_ip,
                          group='compute')

    def add_node(self,
                 hostname: typing.Optional[str] = None,
                 address: typing.Optional[str] = None,
                 group: typing.Optional[str] = None,
                 ssh_client: typing.Optional[ssh.SSHClientFixture] = None) \
            -> OpenStackTopologyNode:
        if ssh_client is not None:
            # detect all global addresses from remote server
            try:
                hostname = sh.get_hostname(ssh_client=ssh_client)
            except Exception:
                LOG.exception("Unable to get node hostname from "
                              f"{ssh_client}")
                ssh_client = None
        name = hostname and node_name_from_hostname(hostname) or None

        addresses: typing.List[netaddr.IPAddress] = []
        if address:
            # add manually configure addresses first
            addresses.extend(self._list_addresses(address))
        if hostname:
            # detect more addresses from the hostname
            addresses.extend(self._list_addresses(hostname))
        addresses = tobiko.select(remove_duplications(addresses))

        try:
            node = self.get_node(name=name, address=addresses)
        except _exception.NoSuchOpenStackTopologyNode:
            node = None

        node = node or self._add_node(addresses=addresses,
                                      hostname=hostname,
                                      ssh_client=ssh_client)

        if group:
            # Add group anyway even if the node hasn't been added
            group_nodes = self.add_group(group=group)
            if node and node not in group_nodes:
                group_nodes.append(node)
                node.add_group(group=group)

        return node

    def _add_node(self,
                  addresses: typing.List[netaddr.IPAddress],
                  hostname: str = None,
                  ssh_client: typing.Optional[ssh.SSHClientFixture] = None):
        if ssh_client is None:
            ssh_client = self._ssh_connect(addresses=addresses)
        addresses.extend(self._list_addresses_from_host(ssh_client=ssh_client))
        addresses = tobiko.select(remove_duplications(addresses))
        hostname = hostname or sh.get_hostname(ssh_client=ssh_client)
        name = node_name_from_hostname(hostname)
        try:
            node = self._names[name]
        except KeyError:
            LOG.debug("Add topology node:\n"
                      f" - name: {name}\n"
                      f" - hostname: {hostname}\n"
                      f" - login: {ssh_client.login}\n"
                      f" - addresses: {addresses}\n")
            self._names[name] = node = self.create_node(name=name,
                                                        hostname=hostname,
                                                        ssh_client=ssh_client,
                                                        addresses=addresses)

        for address in addresses:
            address_node = self._addresses.setdefault(address, node)
            if address_node is not node:
                LOG.error(f"Address '{address}' of node '{name}' is already "
                          f"used by node '{address_node.name}'")
        return node

    def get_node(self, name=None, hostname=None, address=None):
        name = name or (hostname and node_name_from_hostname(hostname))
        details = {}
        if name:
            tobiko.check_valid_type(name, six.string_types)
            details['name'] = name
            try:
                return self._names[name]
            except KeyError:
                pass
        if address:
            details['address'] = address
            for address in self._list_addresses(address):
                try:
                    return self._addresses[address]
                except KeyError:
                    pass
        raise _exception.NoSuchOpenStackTopologyNode(details=details)

    def create_node(self, name, ssh_client, **kwargs):
        return OpenStackTopologyNode(topology=self, name=name,
                                     ssh_client=ssh_client, **kwargs)

    @property
    def nodes(self):
        return tobiko.select(self.get_node(name)
                             for name in self._names)

    def add_group(self, group: str) -> tobiko.Selection:
        try:
            return self._groups[group]
        except KeyError:
            self._groups[group] = nodes = self.create_group()
            return nodes

    @staticmethod
    def create_group() -> tobiko.Selection[OpenStackTopologyNode]:
        return tobiko.Selection()

    def get_group(self, group) -> tobiko.Selection[OpenStackTopologyNode]:
        try:
            return self._groups[group]
        except KeyError as ex:
            raise _exception.NoSuchOpenStackTopologyNodeGroup(
                group=group) from ex

    def get_groups(self, groups) -> tobiko.Selection[OpenStackTopologyNode]:
        nodes: tobiko.Selection[OpenStackTopologyNode] = tobiko.Selection()
        for group in groups:
            nodes.extend(self.get_group(group))
        return nodes

    @property
    def groups(self) -> typing.List[str]:
        return list(self._groups)

    def _ssh_connect(self, addresses: typing.List[netaddr.IPAddress],
                     **connect_params) -> ssh.SSHClientFixture:

        try:
            return _connection.ssh_connect(addresses, **connect_params)
        except _connection.UreachableSSHServer:
            for proxy_node in self.nodes:
                proxy_client = proxy_node.ssh_client
                if proxy_client:
                    LOG.debug("Try connecting through a proxy node "
                              f"'{proxy_node.name}'")
                    try:
                        return self._ssh_connect_with_proxy_client(
                            addresses, proxy_client, **connect_params)
                    except _connection.UreachableSSHServer:
                        pass
            raise

    def _ssh_connect_with_proxy_client(self, addresses, proxy_client,
                                       **connect_params) -> \
            ssh.SSHClientFixture:
        ssh_client = _connection.ssh_connect(addresses,
                                             proxy_client=proxy_client,
                                             **connect_params)
        addresses = self._list_addresses_from_host(ssh_client=ssh_client)
        try:
            LOG.debug("Try connecting through an address that doesn't require "
                      "an SSH proxy host")
            return _connection.ssh_connect(addresses, **connect_params)
        except _connection.UreachableSSHServer:
            return ssh_client

    @property
    def ip_version(self) -> typing.Optional[int]:
        ip_version = self.config.conf.ip_version
        return ip_version and int(ip_version) or None

    def _list_addresses_from_host(self, ssh_client: ssh.SSHClientFixture):
        return ip.list_ip_addresses(ssh_client=ssh_client,
                                    ip_version=self.ip_version,
                                    scope='global')

    def _list_addresses(self, obj) -> typing.List[netaddr.IPAddress]:
        return _address.list_addresses(obj,
                                       ip_version=self.ip_version,
                                       ssh_config=True)


def get_openstack_topology(topology_class: typing.Type = None) -> \
        OpenStackTopology:
    if topology_class:
        if not issubclass(topology_class, OpenStackTopology):
            raise TypeError(f"'{topology_class}' is not subclass of "
                            f"'{OpenStackTopology}'")
    else:
        topology_class = get_default_openstack_topology_class()
    return tobiko.setup_fixture(topology_class)


DEFAULT_TOPOLOGY_CLASS = OpenStackTopology


def node_name_from_hostname(hostname):
    return hostname.split('.', 1)[0].lower()


def remove_duplications(items: typing.List) -> typing.List:
    # use all items as dictionary keys to remove duplications
    mapping = collections.OrderedDict((k, None) for k in items)
    return list(mapping.keys())
