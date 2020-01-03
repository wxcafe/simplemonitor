# coding=utf-8
"""Network-related monitors for SimpleMonitor."""

import datetime
import json
import re
import socket
import subprocess
import sys
from typing import List, Pattern, Tuple, cast

import requests
from requests.auth import HTTPBasicAuth

from .monitor import Monitor, register


@register
class MonitorHTTP(Monitor):
    """Check an HTTP server is working right.

    We can either check that we get a 200 OK back, or we can check for a regexp match in the page.
    """

    url = ""
    regexp = None
    regexp_text = ""
    allowed_codes = []  # type: List[int]

    type = "http"

    # optional - for HTTPS client authentication only
    certfile = None
    keyfile = None

    # optional - headers
    headers = None

    def __init__(self, name: str, config_options: dict) -> None:
        Monitor.__init__(self, name, config_options)
        self.url = Monitor.get_config_option(config_options, "url", required=True)

        regexp = Monitor.get_config_option(config_options, "regexp")
        if regexp is not None:
            self.regexp = re.compile(regexp)
            self.regexp_text = regexp
        if not regexp:
            self.allowed_codes = Monitor.get_config_option(
                config_options, "allowed_codes", default=[200], required_type="[int]"
            )
        else:
            self.allowed_codes = [200]

        # optionnal - for HTTPS client authentication only
        # in this case, certfile is required
        self.certfile = config_options.get("certfile")
        self.keyfile = config_options.get("keyfile")
        if self.certfile and not self.keyfile:
            self.keyfile = self.certfile
        if not self.certfile and self.keyfile:
            raise ValueError("config option keyfile is set but certfile is not")

        self.headers = config_options.get("headers")
        if self.headers:
            self.headers = json.loads(self.headers)

        self.verify_hostname = Monitor.get_config_option(
            config_options, "verify_hostname", default=True, required_type="bool"
        )

        self.request_timeout = Monitor.get_config_option(
            config_options, "timeout", default=5, required_type="int"
        )

        self.username = config_options.get("username")
        self.password = config_options.get("password")

    def run_test(self) -> bool:
        start_time = datetime.datetime.now()
        end_time = None
        try:
            if self.certfile is None and self.username is None:
                r = requests.get(
                    self.url,
                    timeout=self.request_timeout,
                    verify=self.verify_hostname,
                    headers=self.headers,
                )
            elif self.certfile is None and self.username is not None:
                r = requests.get(
                    self.url,
                    timeout=self.request_timeout,
                    auth=HTTPBasicAuth(self.username, self.password),
                    verify=self.verify_hostname,
                    headers=self.headers,
                )
            else:
                r = requests.get(
                    self.url,
                    timeout=self.request_timeout,
                    cert=(self.certfile, self.keyfile),
                    verify=self.verify_hostname,
                    headers=self.headers,
                )

            end_time = datetime.datetime.now()
            load_time = end_time - start_time
            if r.status_code not in self.allowed_codes:
                return self.record_fail(
                    "Got status '{0} {1}' instead of {2}".format(
                        r.status_code, r.reason, self.allowed_codes
                    )
                )
            if self.regexp is None:
                return self.record_success(
                    "%s in %0.2fs"
                    % (
                        r.status_code,
                        (load_time.seconds + (load_time.microseconds / 1000000.2)),
                    )
                )
            matches = self.regexp.search(r.text)
            if matches:
                return self.record_success(
                    "%s in %0.2fs"
                    % (
                        r.status_code,
                        (load_time.seconds + (load_time.microseconds / 1000000.2)),
                    )
                )
            return self.record_fail(
                "Got '{0} {1}' but couldn't match /{2}/ in page.".format(
                    r.status_code, r.reason, self.regexp_text
                )
            )
        except requests.exceptions.RequestException as e:
            return self.record_fail(
                "Requests exception while opening URL: {0}".format(e)
            )
        except Exception as e:
            return self.record_fail("Exception while trying to open url: {0}".format(e))

    def describe(self) -> str:
        """Explains what we do."""
        if self.regexp is None:
            message = "Checking that accessing %s returns HTTP/200 OK" % self.url
        else:
            message = (
                "Checking that accessing %s returns HTTP/200 OK and that /%s/ matches the page"
                % (self.url, self.regexp_text)
            )
        return message

    def get_params(self) -> Tuple:
        return (self.url, self.regexp_text, self.allowed_codes)


@register
class MonitorTCP(Monitor):
    """TCP port monitor"""

    host = ""
    port = 0
    type = "tcp"

    def __init__(self, name: str, config_options: dict) -> None:
        """Constructor"""
        Monitor.__init__(self, name, config_options)
        self.host = Monitor.get_config_option(config_options, "host", required=True)
        self.port = cast(
            int,
            Monitor.get_config_option(
                config_options, "port", required=True, required_type="int", minimum=0
            ),
        )

    def run_test(self) -> bool:
        """Check the port is open on the remote host"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(5.0)
            s.connect((self.host, self.port))
        except Exception:
            return self.record_fail()
        s.close()
        return self.record_success()

    def describe(self) -> str:
        """Explains what this instance is checking"""
        return "checking for open tcp socket on %s:%d" % (self.host, self.port)

    def get_params(self) -> Tuple:
        return (self.host, self.port)


@register
class MonitorHost(Monitor):
    """Ping a host to make sure it's up"""

    host = ""
    ping_command = ""
    ping_regexp = ""
    type = "host"
    time_regexp = ""
    r = None  # type: Pattern[str]
    r2 = None  # type: Pattern[str]

    def __init__(self, name: str, config_options: dict) -> None:
        """
        Note: We use -w/-t on Windows/POSIX to limit the amount of time we wait to 5 seconds.
        This is to stop ping holding things up too much. A machine that can't ping back in <5s is
        a machine in trouble anyway, so should probably count as a failure.
        """
        Monitor.__init__(self, name, config_options)
        ping_ttl = Monitor.get_config_option(
            config_options, "ping_ttl", required_type="int", minimum=0, default=5
        )
        ping_ms = str(ping_ttl * 1000)
        ping_ttl = str(ping_ttl)
        platform = sys.platform
        if platform in ["win32", "cygwin"]:
            self.ping_command = "ping -n 1 -w " + ping_ms + " %s"
            self.ping_regexp = r"Reply from [0-9a-f:.]+:.+time[=<]\d+ms"
            self.time_regexp = r"Average = (?P<ms>\d+)ms"
        elif platform.startswith("freebsd") or platform.startswith("darwin"):
            self.ping_command = "ping -c1 -t" + ping_ttl + " %s"
            self.ping_regexp = "bytes from"
            self.time_regexp = r"min/avg/max/stddev = [\d.]+/(?P<ms>[\d.]+)/"
        elif platform.startswith("linux"):
            self.ping_command = "ping -c1 -W" + ping_ttl + " %s"
            self.ping_regexp = "bytes from"
            self.time_regexp = r"min/avg/max/stddev = [\d.]+/(?P<ms>[\d.]+)/"
        else:
            RuntimeError("Don't know how to run ping on this platform, help!")

        self.host = Monitor.get_config_option(config_options, "host", required=True)

    def run_test(self) -> bool:
        success = False
        pingtime = 0.0

        if isinstance(self.r, str):
            self.monitor_logger.debug("Creating pre-compiled regexp")
            self.r = re.compile(self.ping_regexp)
            self.r2 = re.compile(self.time_regexp)

        try:
            cmd = (self.ping_command % self.host).split(" ")
            output = subprocess.check_output(cmd)
            for line in str(output).split("\n"):
                matches = self.r.search(line)
                if matches:
                    success = True
                else:
                    matches = self.r2.search(line)
                    if matches:
                        pingtime = float(matches.group("ms"))
        except Exception as e:
            return self.record_fail(str(e))
        if success:
            if pingtime > 0:
                return self.record_success("%sms" % pingtime)
            return self.record_success()
        return self.record_fail()

    def describe(self) -> str:
        """Explains what this instance is checking"""
        return "checking host %s is pingable" % self.host

    def get_params(self) -> Tuple:
        return (self.host,)


@register
class MonitorDNS(Monitor):
    """Monitor DNS server."""

    type = "dns"
    path = ""
    command = "dig"

    def __init__(self, name: str, config_options: dict) -> None:
        Monitor.__init__(self, name, config_options)
        self.path = Monitor.get_config_option(config_options, "record", required=True)

        self.desired_val = Monitor.get_config_option(config_options, "desired_val")

        self.server = Monitor.get_config_option(config_options, "server")

        self.params = [self.command]

        if self.server:
            self.params.append("@%s" % self.server)

        self.rectype = Monitor.get_config_option(config_options, "record_type")
        if self.rectype:
            self.params.append("-t")
            self.params.append(config_options["record_type"])

        self.params.append(self.path)
        self.params.append("+short")

    def run_test(self) -> bool:
        try:
            result = subprocess.check_output(self.params).decode("utf-8")
            result = result.strip()
            if result is None or result == "":
                if self.desired_val != "nxdomain":
                    return self.record_fail("failed to resolve %s" % self.path)
                return self.record_success("successfully did not resolve")
            if self.desired_val and set(result.split("\n")) != set(
                self.desired_val.split("\n")
            ):
                return self.record_fail(
                    "resolved DNS record is unexpected: %s != %s"
                    % (self.desired_val, result)
                )
            return self.record_success()
        except subprocess.CalledProcessError as e:
            return self.record_fail(
                "Command '%s' exited non-zero (%d)"
                % (" ".join(self.params), e.returncode)
            )
        except Exception as e:
            return self.record_fail(
                "Exception while executing '%s': %s" % (" ".join(self.params), e)
            )

    def describe(self) -> str:
        if self.desired_val:
            end_part = "resolves to %s" % self.desired_val
        else:
            end_part = "is resolvable"

        if self.rectype:
            mid_part = "%s record %s" % (self.rectype, self.path)
        else:
            mid_part = "record %s" % self.path

        if self.server:
            very_end_part = " at %s" % self.server
        else:
            very_end_part = ""
        return "Checking that DNS %s %s%s" % (mid_part, end_part, very_end_part)

    def get_params(self) -> Tuple:
        return (self.path,)
