# Copyright 2022 Red Hat
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

from collections import abc
import typing

import netaddr

import tobiko
from tobiko.openstack.neutron import _client
from tobiko.openstack.neutron import _network


SubnetType = typing.Dict[str, typing.Any]
SubnetIdType = typing.Union[str, SubnetType]


def get_subnet_id(subnet: SubnetIdType) -> str:
    if isinstance(subnet, str):
        return subnet
    else:
        return subnet['id']


def get_subnet(subnet: SubnetIdType,
               client: _client.NeutronClientType = None,
               **params) -> SubnetType:
    subnet_id = get_subnet_id(subnet)
    try:
        return _client.neutron_client(client).show_subnet(
            subnet_id, **params)['subnet']
    except _client.NotFound as ex:
        raise NoSuchSubnet(id=subnet_id) from ex


def create_subnet(client: _client.NeutronClientType = None,
                  network: _network.NetworkIdType = None,
                  add_cleanup=True,
                  **params) -> SubnetType:
    if 'network_id' not in params:
        if network is None:
            from tobiko.openstack import stacks
            network_id = tobiko.setup_fixture(
                stacks.NetworkStackFixture).network_id
        else:
            network_id = _network.get_network_id(network)
        params['network_id'] = network_id
    subnet = _client.neutron_client(client).create_subnet(
        body={'subnet': params})['subnet']
    if add_cleanup:
        tobiko.add_cleanup(cleanup_subnet, subnet=subnet, client=client)
    return subnet


def cleanup_subnet(subnet: SubnetIdType,
                   client: _client.NeutronClientType = None):
    try:
        delete_subnet(subnet=subnet, client=client)
    except NoSuchSubnet:
        pass


def delete_subnet(subnet: SubnetIdType,
                  client: _client.NeutronClientType = None):
    subnet_id = get_subnet_id(subnet)
    try:
        _client.neutron_client(client).delete_subnet(subnet_id)
    except _client.NotFound as ex:
        raise NoSuchSubnet(id=subnet_id) from ex


def list_subnets(client: _client.NeutronClientType = None,
                 ip_version: int = None,
                 **params) -> tobiko.Selection[SubnetType]:
    if ip_version is not None:
        params['ip_version'] = ip_version
    subnets = _client.neutron_client(client).list_subnets(**params)
    if isinstance(subnets, abc.Mapping):
        subnets = subnets['subnets']
    return tobiko.select(subnets)


def list_subnet_cidrs(client: _client.NeutronClientType = None,
                      **params) -> tobiko.Selection[netaddr.IPNetwork]:
    return tobiko.select(netaddr.IPNetwork(subnet['cidr'])
                         for subnet in list_subnets(client=client, **params))


def find_subnet(client: _client.NeutronClientType = None,
                unique=False,
                default: SubnetType = None,
                **params) -> SubnetType:
    """Look for a subnet matching some property values"""
    subnets = list_subnets(client=client, **params)
    if default is None or subnets:
        if unique:
            return subnets.unique
        else:
            return subnets.first
    else:
        return default


class NoSuchSubnet(tobiko.ObjectNotFound):
    message = "No such subnet found for {id!r}"
