try:
    import requests

    requests_available = True
except ImportError:
    requests_available = False

from typing import cast

from Monitors.monitor import Monitor
from util import AlerterConfigurationError, format_datetime

from .alerter import Alerter, register


@register
class FortySixElksAlerter(Alerter):
    """Send SMS alerts using the 46elks SMS service.

    Account required, see https://www.46elks.com/"""

    type = "46elks"

    def __init__(self, config_options: dict) -> None:
        Alerter.__init__(self, config_options)
        if not requests_available:
            self.alerter_logger.critical(
                "Requests package is not available, cannot use FortySixElksAlerter."
            )
            self.alerter_logger.critical("Try: pip install -r requirements.txt")
            return

        self.username = cast(
            str,
            Alerter.get_config_option(
                config_options, "username", required=True, allow_empty=False
            ),
        )
        self.password = cast(
            str,
            Alerter.get_config_option(
                config_options, "password", required=True, allow_empty=False
            ),
        )
        self.target = cast(
            str,
            Alerter.get_config_option(
                config_options, "target", required=True, allow_empty=False
            ),
        )

        self.sender = cast(
            str, Alerter.get_config_option(config_options, "sender", default="SmplMntr")
        )
        if self.sender[0] == "+" and self.sender[1:].isdigit():
            # sender is phone number
            pass
        elif len(self.sender) < 3:
            raise AlerterConfigurationError(
                "SMS sender name must be at least 3 chars long"
            )
        elif len(self.sender) > 11:
            self.alerter_logger.warning("truncating SMS sender name to 11 chars")
            self.sender = self.sender[:11]

        self.api_host = Alerter.get_config_option(
            config_options, "api_host", default="api.46elks.com"
        )

        self.support_catchup = True

    def send_alert(self, name: str, monitor: Monitor) -> None:
        """Send an SMS alert."""

        if not monitor.urgent:
            return

        alert_type = self.should_alert(monitor)
        message = ""
        url = ""

        (days, hours, minutes, seconds) = monitor.get_downtime()
        if alert_type == "":
            return
        elif alert_type == "catchup":
            message = "catchup: %s failed on %s at %s (%d+%02d:%02d:%02d)\n%s" % (
                name,
                monitor.running_on,
                format_datetime(monitor.first_failure_time()),
                days,
                hours,
                minutes,
                seconds,
                monitor.get_result(),
            )
            if len(message) > 160:
                self.alerter_logger.warning("Truncating SMS message to 160 chars.")
                message = message[:156] + "..."
            url = "https://{}/a1/SMS".format(self.api_host)
            auth = (self.username, self.password)
            params = {"from": self.sender, "to": self.target, "message": message}
        elif alert_type == "failure":
            message = "%s failed on %s at %s (%d+%02d:%02d:%02d)\n%s" % (
                name,
                monitor.running_on,
                format_datetime(monitor.first_failure_time()),
                days,
                hours,
                minutes,
                seconds,
                monitor.get_result(),
            )
            if len(message) > 160:
                self.alerter_logger.warning("Truncating SMS message to 160 chars.")
                message = message[:156] + "..."
            url = "https://{}/a1/SMS".format(self.api_host)
            auth = (self.username, self.password)
            params = {"from": self.sender, "to": self.target, "message": message}
        else:
            # we don't handle other types of message
            pass

        if url == "":
            return

        if not self.dry_run:
            try:
                response = requests.post(url, data=params, auth=auth)
                s = response.json()
                if s["status"] not in ("created", "delivered"):
                    self.alerter_logger.error("Unable to send SMS: %s", s)
                    self.available = False
            except Exception:
                self.alerter_logger.exception("SMS sending failed")
                self.available = False
        else:
            self.alerter_logger.info("dry_run: would send SMS: %s", url)
        return
