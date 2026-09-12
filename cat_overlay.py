#!/usr/bin/env python3
"""
Desktop Cat Widget - Always-on-top animated desktop companion
Cross-platform entry point for Linux and Windows.
"""

import sys

if sys.platform == "win32":
    from cat_overlay_windows import DesktopCatAppWindows as DesktopCatApp
else:
    from cat_overlay_linux import DesktopCatAppLinux as DesktopCatApp


def main():
    app = DesktopCatApp()
    app.run()


if __name__ == "__main__":
    main()
