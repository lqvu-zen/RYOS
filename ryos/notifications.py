"""Toast notifications and GitHub update check."""
import json
import subprocess
import sys
import urllib.request

_RELEASES_API = "https://api.github.com/repos/lqvu-zen/RYOS/releases/latest"
_RELEASES_PAGE = "https://github.com/lqvu-zen/RYOS/releases/latest"


def _show_notification(title: str, body: str) -> None:
    """Fire a Windows toast notification (fire-and-forget, Windows 10/11 only)."""
    if sys.platform != "win32":
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
    except Exception:
        pass


def _parse_version(tag: str) -> tuple:
    try:
        return tuple(int(x.split("-")[0]) for x in tag.lstrip("v").split("."))
    except Exception:
        return (0,)


def _fetch_latest_release() -> tuple[str, str] | None:
    try:
        req = urllib.request.Request(
            _RELEASES_API, headers={"User-Agent": "RYOS-update-check"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return data["tag_name"], data["html_url"]
    except Exception:
        return None
