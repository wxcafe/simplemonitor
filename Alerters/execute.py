# coding=utf-8
import shlex
import subprocess
from typing import cast

from Monitors.monitor import Monitor
from util import AlerterConfigurationError, format_datetime

from .alerter import Alerter, register


@register
class ExecuteAlerter(Alerter):
    """Execute an external command when a monitor fails or recovers."""

    type = "execute"

    def __init__(self, config_options: dict) -> None:
        Alerter.__init__(self, config_options)

        self.fail_command = cast(
            str,
            Alerter.get_config_option(
                config_options, "fail_command", allow_empty=False
            ),
        )
        self.success_command = cast(
            str,
            Alerter.get_config_option(
                config_options, "success_command", allow_empty=False
            ),
        )
        self.catchup_command = cast(
            str,
            Alerter.get_config_option(
                config_options, "catchup_command", allow_empty=False
            ),
        )
        if (
            self.fail_command is None
            and self.success_command is None
            and self.catchup_command is None
        ):
            raise AlerterConfigurationError("execute alerter has no commands defined")

    def send_alert(self, name: str, monitor: Monitor) -> None:
        type_ = self.should_alert(monitor)
        command = None
        (days, hours, minutes, seconds) = monitor.get_downtime()
        if monitor.is_remote():
            host = monitor.running_on
        else:
            host = self.hostname

        if type_ == "":
            return
        elif type_ == "failure":
            command = self.fail_command
        elif type_ == "success":
            command = self.success_command
        elif type_ == "catchup":
            if self.catchup_command == "fail_command":
                command = self.fail_command
        else:
            self.alerter_logger.error("Unknown alert type %s", type_)
            return

        if command is None:
            return

        command = command.format(
            hostname=host,
            name=name,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            failed_at=format_datetime(monitor.first_failure_time()),
            virtual_fail_count=monitor.virtual_fail_count(),
            info=monitor.get_result(),
            description=monitor.describe(),
            last_virtual_fail_count=monitor.last_virtual_fail_count(),
        )

        if not self.dry_run:
            self.alerter_logger.debug("About to execute command: %s", command)
            try:
                subprocess.call(shlex.split(command))
            except Exception:
                self.alerter_logger.exception(
                    "Exception encountered running command: %s", command
                )
            if self.debug:
                self.alerter_logger.debug("Command has finished.")
        else:
            self.alerter_logger.info("Would run command: %s", command)
