# Yandex Disk indicator and control

`ydi` provides indicator and control for [yandex-disk](https://yandex.ru/support/yandex-360/customers/disk/desktop/linux/ru/) on Linux distributions that conform to freedesktop.org standard. 

## Usage summary

`ydi` works as an AppIndicator for Yandex Disk activity. The icon will change to reflect the current status of the syncronization core. Menu items are self explanatory. Clicking Yandex Disk folder path will open your file manager at that path. Preferences allow changing the status update frequency and icon theme.

<img src="docs/ydiss.png" alt="YDI menu" width="30%"/>

## Installation details

The recommended method is to install the deb package.

`ydi` deb package installs itself in /opt/ydi. yandex-disk deb installation is triggered during `ydi` installation but is not controlled. It is implied that yandex-disk creates ~/.config/yandex-disk folder. The settings file `ydi.cfg` will be placed there. `ydi` will also put itself into "Run at startup" group.

The installtion script also installs a small shell script (yd_keep_alive.sh) and registers it with `cron` to run every hour. yandex-disk daemon is prone to stalling in "no internet connection" error state when the computer suspends on power settings. This script checks whether yandex-disk daemon is running and (re)starts it if it is paused on error.

Should you wish to, it is also possible to use the Python files directly. Place the contents of this repository into a convineient folder and make `ydi` script executable before you run it.

	chmod +x ydi
	./ydi

## Limitations

> `ydi` will not configure yandex-disk daemon for you. You will still have to setup the daemon in the way Yandex documentation [explains it](https://yandex.ru/support/yandex-360/customers/disk/desktop/linux/ru/).

