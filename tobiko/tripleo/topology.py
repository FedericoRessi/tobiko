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

import re
import typing

from oslo_log import log

from tobiko.openstack import topology
from tobiko.tripleo import overcloud
from tobiko.tripleo import undercloud


LOG = log.getLogger(__name__)


class TripleoTopology(topology.OpenStackTopology):

    agent_to_service_name_mappings = {
        'neutron-dhcp-agent': 'tripleo_neutron_dhcp',
        'neutron-l3-agent': 'tripleo_neutron_l3_agent',
        'neutron-ovs-agent': 'tripleo_neutron_ovs_agent',
    }

    has_containers = True

    # TODO: add more known subgrups here
    known_subgroups: typing.List[str] = ['controller', 'compute']

    def discover_nodes(self):
        self.discover_undercloud_nodes()
        self.discover_overcloud_nodes()

    def discover_undercloud_nodes(self):
        if undercloud.has_undercloud():
            config = undercloud.undercloud_host_config()
            ssh_client = undercloud.undercloud_ssh_client()
            self.add_node(address=config.hostname,
                          group='undercloud',
                          ssh_client=ssh_client)

    def discover_overcloud_nodes(self):
        if overcloud.has_overcloud():
            for server in overcloud.list_overcloud_nodes():
                config = overcloud.overcloud_host_config(server.name)
                ssh_client = overcloud.overcloud_ssh_client(server.name)
                node = self.add_node(address=config.hostname,
                                     group='overcloud',
                                     ssh_client=ssh_client)
                self.discover_overcloud_node_subgroups(node)
        else:
            super(TripleoTopology, self).discover_nodes()

    def discover_overcloud_node_subgroups(self, node):
        # set of subgroups extracted from node name
        subgroups: typing.Set[str] = set()

        # extract subgroups names from node name
        subgroups.update(subgroup
                         for subgroup in node.name.split('-')
                         if is_valid_overcloud_group_name(group_name=subgroup,
                                                          node_name=node.name))

        # add all those known subgroups names that are contained in
        # the node name (controller, compute, ...)
        subgroups.update(subgroup
                         for subgroup in self.known_subgroups
                         if subgroup in node.name)

        # bind node to discovered subgroups
        if subgroups:
            for subgroup in sorted(subgroups):
                LOG.debug("Add node '%s' to subgroup '%s'", node.name,
                          subgroup)
                self.add_node(hostname=node.name, group=subgroup)
        else:
            LOG.warning("Unable to obtain any node subgroup from node "
                        "name: '%s'", node.name)
        return subgroups


def is_valid_overcloud_group_name(group_name: str, node_name: str = None):
    if not group_name:
        return False
    if group_name in ['overcloud', node_name]:
        return False
    if is_number(group_name):
        return False
    return True


def is_number(text: str):
    try:
        float(text)
    except ValueError:
        return False
    else:
        return True


def setup_tripleo_topology():
    if undercloud.has_undercloud() or overcloud.has_overcloud():
        topology.set_default_openstack_topology_class(
            'tobiko.tripleo.topology.TripleoTopology')


def get_ip_to_nodes_dict(openstack_nodes=None):
    if not openstack_nodes:
        openstack_nodes = topology.list_openstack_nodes(group='overcloud')
    ip_to_nodes_dict = {str(node.public_ip): node.name for node in
                        openstack_nodes}
    return ip_to_nodes_dict


def str_is_not_ip(check_str):
    letters = re.compile('[A-Za-z]')
    return bool(letters.match(check_str))


def ip_to_hostname(oc_ip):
    return get_ip_to_nodes_dict()[oc_ip]


def actual_node_groups(groups):
    """return only existing node groups"""
    return set(groups).intersection(topology.list_openstack_node_groups())
