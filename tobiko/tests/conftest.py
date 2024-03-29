# Copyright (c) 2020 Red Hat
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

from datetime import datetime
import os
import subprocess

from oslo_log import log
from py.xml import html  # pylint: disable=no-name-in-module,import-error
import pytest
from pytest_html import plugin as html_plugin

import tobiko

LOG = log.getLogger(__name__)


def normalize_path(path):
    return os.path.realpath(os.path.expanduser(path))


TOP_DIR = normalize_path(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# Output dirs
REPORT_DIR = os.path.realpath(os.path.expanduser(
    os.environ.get('TOBIKO_TEST_PATH') or
    os.environ.get('TOX_REPORT_DIR') or
    os.getcwd()))

REPORT_NAME = (
    os.environ.get('TOBIKO_REPORT_NAME') or
    os.environ.get('TOX_REPORT_NAME') or
    'tobiko_results')

REPORT_PREFIX = os.path.join(REPORT_DIR, REPORT_NAME)

REPORT_HTML = (
    os.environ.get('TOBIKO_REPORT_HTML') or
    os.environ.get('TOX_REPORT_HTML') or
    REPORT_PREFIX + '.html')


@pytest.hookimpl
def pytest_configure(config):
    configure_metadata(config)
    configure_caplog(config)
    configure_timeout(config)
    configure_junitxml(config)
    configure_html(config)


def configure_metadata(config):
    # pylint: disable=protected-access
    from tobiko import version
    config._metadata["Tobiko Version"] = version.release
    git_commit = subprocess.check_output(
        ['git', 'log', '-n', '1'],
        universal_newlines=True).replace('\n', '<br>')
    config._metadata["Tobiko Git Commit"] = git_commit
    git_release = subprocess.check_output(
        ['git', 'describe', '--tags'],
        universal_newlines=True).replace('\n', '<br>')
    config._metadata["Tobiko Git Release"] = git_release


def configure_caplog(config):
    tobiko_config = tobiko.tobiko_config()

    if tobiko_config.logging.capture_log:
        if tobiko_config.debug:
            level = 'DEBUG'
        else:
            level = 'INFO'
    else:
        level = 'FATAL'
    for key in ['log_level',
                'log_file_level',
                'log_cli_level']:
        set_default_inicfg(config, key, level)

    line_format: str = tobiko_config.logging.line_format
    if line_format:
        # instance and color are not supported by pytest
        line_format = line_format.replace('%(instance)s', '')
        line_format = line_format.replace('%(color)s', '')
        if line_format:
            for key in ['log_format',
                        'log_file_format',
                        'log_cli_format']:
                set_default_inicfg(config, key, line_format)

    date_format = tobiko_config.logging.date_format
    if date_format:
        for key in ['log_date_format',
                    'log_file_date_format',
                    'log_cli_date_format']:
            set_default_inicfg(config, key, date_format)


def configure_junitxml(config):
    config.inicfg['junit_suite_name'] = REPORT_NAME


def configure_html(config):
    if config.pluginmanager.hasplugin('html'):
        htmlpath = config.getoption('htmlpath')
        if htmlpath is None:
            config.option.htmlpath = REPORT_HTML
            htmlpath = config.getoption('htmlpath')
        assert htmlpath is not None

        html_plugin.HTMLReport = HTMLReport


class HTMLReport(html_plugin.HTMLReport):

    session = None
    last_html_generation: tobiko.Seconds = None

    def pytest_sessionstart(self, session):
        super().pytest_sessionstart(session)
        self.session = session

    def pytest_runtest_logreport(self, report):
        super().pytest_runtest_logreport(report)

        # Avoid report regeneration ad an interval smaller than 10 seconds
        now = tobiko.time()
        if (self.last_html_generation is not None and
                now - self.last_html_generation < 10.):
            return
        self.last_html_generation = now

        LOG.debug("Update HTML test report files...")
        temp_report = html_plugin.HTMLReport(logfile=self.logfile,
                                             config=self.config)
        # pylint: disable=attribute-defined-outside-init
        temp_report.suite_start_time = self.suite_start_time
        temp_report.reports = dict(self.reports)
        temp_report.pytest_sessionfinish(self.session)
        LOG.debug("HTML test report files updated")


def set_default_inicfg(config, key, default):
    value = config.inicfg.setdefault(key, default)
    if value == default:
        LOG.debug(f"Set default inicfg: {key} = {value!r}")


class TestRunnerTimeoutManager(tobiko.SharedFixture):
    timeout: tobiko.Seconds = None
    deadline: tobiko.Seconds = None

    def setup_fixture(self):
        tobiko_config = tobiko.tobiko_config()
        self.timeout = tobiko_config.testcase.test_runner_timeout
        if self.timeout is None:
            LOG.info('Test runner timeout is disabled')
        else:
            LOG.info('Test runner timeout is enabled: '
                     f'timeout is {self.timeout} seconds')
            self.deadline = tobiko.time() + self.timeout

    @classmethod
    def check_test_runner_timeout(cls):
        self = tobiko.setup_fixture(cls)
        if self.deadline is not None:
            time_left = self.deadline - tobiko.time()
            if time_left <= 0.:
                pytest.skip(
                    f"Test runner execution timed out after {self.timeout} "
                    f"seconds",
                    allow_module_level=True)
            else:
                LOG.debug('Test runner timeout is enabled: '
                          f'{time_left} seconds left')


def check_test_runner_timeout():
    TestRunnerTimeoutManager.check_test_runner_timeout()


def configure_timeout(config):
    tobiko_config = tobiko.tobiko_config()
    default = tobiko_config.testcase.timeout
    if default is not None and default > 0.:
        set_default_inicfg(config, 'timeout', default)


def pytest_html_results_table_header(cells):
    cells.insert(2, html.th("Description"))
    cells.insert(1, html.th("Time", class_="sortable time", col="time"))
    cells.pop()


def pytest_html_results_table_row(report, cells):
    cells.insert(2, html.td(getattr(report, 'description', '')))
    cells.insert(1, html.td(datetime.utcnow(), class_="col-time"))
    cells.pop()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # pylint: disable=unused-argument
    outcome = yield
    report = outcome.get_result()
    report.description = getattr(item.function, '__doc__', '')


def pytest_html_report_title(report):
    report.title = f"Tobiko test results ({REPORT_NAME})"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    # pylint: disable=protected-access
    check_test_runner_timeout()
    tobiko.push_test_case(item._testcase)
    try:
        yield
    finally:
        tobiko.pop_test_case()
