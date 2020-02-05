from __future__ import absolute_import

import testtools
from tobiko.shell import ping
from tobiko.shell import sh
from tobiko.tests.faults.ha import cloud_disruptions
from tobiko.tripleo import pacemaker
from tobiko.tripleo import processes
from tobiko.openstack import stacks
import tobiko


def nodes_health_check():
    # this method will be changed in future commit
    check_pacemaker_resources_health()
    check_overcloud_processes_health()

    # TODO:
    # Test existing created servers
    # ServerStackResourcesTest().test_server_create()


# check vm create with ssh and ping checks
def check_vm_create(stack_name):
    '''stack_name: unique stack name ,
    so that each time a new vm is created'''
    # create a vm
    stack = stacks.CirrosServerStackFixture(
        stack_name=stack_name)
    tobiko.reset_fixture(stack)
    stack.wait_for_create_complete()
    # Test SSH connectivity to floating IP address
    sh.get_hostname(ssh_client=stack.ssh_client)

    # Test ICMP connectivity to floating IP address
    ping.ping_until_received(
        stack.floating_ip_address).assert_replied()


# check cluster failed statuses
def check_pacemaker_resources_health():
    return pacemaker.PacemakerResourcesStatus().all_healthy


def check_overcloud_processes_health():
    return processes.OvercloudProcessesStatus(
            ).basic_overcloud_processes_running


class RebootNodesTest(testtools.TestCase):

    """ HA Tests: run health check -> disruptive action -> health check
    disruptive_action: a function that runs some
    disruptive scenarion on a overcloud"""

    def test_reboot_controllers_recovery(self):
        nodes_health_check()
        cloud_disruptions.reset_all_controller_nodes()
        nodes_health_check()
        check_vm_create(stack_name=self.id())

    def test_reboot_computes_recovery(self):
        nodes_health_check()
        cloud_disruptions.reset_all_compute_nodes(hard_reset=True)
        nodes_health_check()
        check_vm_create(stack_name=self.id())

# [..]
# more tests to folow
# run health checks
# os faults stop rabbitmq service on one controller
# run health checks again
