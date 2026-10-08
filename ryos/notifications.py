"""Toast notifications and GitHub update check."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from .logger import get_logger

_log = get_logger("notifications")

_RELEASES_API = "https://api.github.com/repos/lqvu-zen/RYOS/releases/latest"
_RELEASES_PAGE = "https://github.com/lqvu-zen/RYOS/releases/latest"


def toasts_blocked() -> bool:
    """True when RYOS_NO_TOASTS=1: test runs and screenshots run real jobs,
    and each finished one popped a toast on the screen someone is using."""
    return os.environ.get("RYOS_NO_TOASTS") == "1"


def _show_notification(title: str, body: str) -> None:
    """Fire a Windows toast notification (fire-and-forget, Windows 10/11 only)."""
    if sys.platform != "win32" or toasts_blocked():
        return
    import base64
    # Use PowerShell's own registered AppId so no app registration is needed.
    _APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    t = title.replace('"', '`"')
    b = body.replace('"', '`"')
    script = f"""
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t1 = $xml.GetElementsByTagName("text").Item(0)
$t2 = $xml.GetElementsByTagName("text").Item(1)
$t1.AppendChild($xml.CreateTextNode("{t}")) | Out-Null
$t2.AppendChild($xml.CreateTextNode("{b}")) | Out-Null
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{_APP_ID}").Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-NoProfile",
             "-EncodedCommand", encoded],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        # Best-effort cosmetic toast (e.g. PowerShell missing / spawn failure);
        # log for diagnosis but never let it stop a job from completing.
        _log.debug("Toast notification failed: %s", e)


def _parse_version(tag: str) -> tuple:
    try:
        return tuple(int(x.split("-")[0]) for x in tag.lstrip("v").split("."))
    except (ValueError, AttributeError):
        # Non-numeric component, or tag isn't a string: sorts lowest.
        return (0,)


def _fetch_latest_release() -> tuple[str, str] | None:
    try:
        req = urllib.request.Request(
            _RELEASES_API, headers={"User-Agent": "RYOS-update-check"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return data["tag_name"], data["html_url"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        # Network down, non-JSON body, or an unexpected response shape: the
        # update check is optional, so log and skip rather than surface an error.
        _log.debug("Update check failed: %s", e)
        return None


# --- what an update check means, for both UIs -----------------------------------
# The fetch is above; these decide what its result means and what to say, so the
# Tk banner and the Qt banner cannot disagree about when an update exists.

NEWER = "newer"
CURRENT = "current"
UNREACHABLE = "unreachable"

UNREACHABLE_NOTICE = ("Update Check",
                      "Could not reach GitHub. Check your internet connection.")


def update_status(result, current: str) -> tuple:
    """(NEWER / CURRENT / UNREACHABLE, tag, url) for a `_fetch_latest_release` result."""
    if result is None:
        return UNREACHABLE, "", ""
    tag, url = result
    if _parse_version(tag) > _parse_version(current):
        return NEWER, tag, url
    return CURRENT, tag, url


def up_to_date_notice(current: str) -> tuple[str, str]:
    return "Up to date", f"You are running the latest version ({current})."


def banner_text(tag: str, current: str, download: str = "") -> str:
    """The window's update banner; ``download`` names the zip that replaces
    this one (buildinfo.download_name), so nobody updates into another kind."""
    get = f" \u2014 get {download}" if download else ""
    return f"🔔  Update available: {tag}  (you have v{current}){get}"


def version_check_text(status: str, tag: str, url: str, current: str,
                       download: str) -> str:
    """What `ryos-cli version --check` says: RYOS Agent has no window for a
    banner."""
    if status == NEWER:
        return (f"RYOS {tag.lstrip('v')} is out (you have {current}). "
                f"Download {download} from {url}")
    if status == CURRENT:
        return f"Up to date: RYOS {current} is the latest."
    return UNREACHABLE_NOTICE[1]
