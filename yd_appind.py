from gi import require_version
require_version('Gtk', '3.0')
from gi.repository import Gtk
try:
	require_version('AppIndicator3', '0.1')
	from gi.repository import AppIndicator3 as AppIndicator
except Exception:
	require_version('AyatanaAppIndicator3', '0.1')
	from gi.repository import AyatanaAppIndicator3 as AppIndicator
require_version('Notify', '0.7')
from gi.repository import Notify

from subprocess import run
from threading import Thread
from time import sleep
import os

from yd_cli import YandexDisk, NoYDCLI

UPDATE_INTERVAL = 1.5

APPINDICATOR_ID = 'com.dandelion-systems.yandexdisk'

class YDIndicator:
	__disk = None
	"""
	yandex-disk CLI interface
	"""
	
	__indicator = None
	"""
	AppIndicator instance.
	"""

	__menu = None
	"""
	Our menu. Some items will change dynamically.
	"""

	__ydm_sync_status = None
	__ydm_quota = None
	__ydm_quota_sub = None
	__ydm_quota_sub_path = None
	__ydm_quota_sub_total = None
	__ydm_quota_sub_used = None
	__ydm_quota_sub_available = None
	__ydm_quota_sub_maxfile = None
	__ydm_quota_sub_trash = None
	__ydm_rsynced = None
	__ydm_rsynced_sub = None
	__ydm_rsynced_sub_files = None
	__ydm_rsynced_sub_dirs = None
	__ydm_start_stop = None
	__ydm_preferences = None
	__ydm_about = None
	__ydm_quit = None

	__daemon = None
	"""
	Menu updates deamon.
	"""

	__monitoring = False
	"""
	Menu updates deamon flag.
	"""

	def __init__(self, disk:YandexDisk):
		# Check if we are running already
		# ...

		# YD status indicator and control
		self.__indicator = AppIndicator.Indicator.new(APPINDICATOR_ID, "YDNormal.png", AppIndicator.IndicatorCategory.SYSTEM_SERVICES)
		self.__indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

		# YD themed icons
		Gtk.Settings.get_default().connect("notify::gtk-theme-name", self.__theme_name_changed)
		self.__theme_name_changed(Gtk.Settings.get_default(), None)

		# YD control menu
		self.__menu = Gtk.Menu()
		self.__indicator.set_menu(self.__menu)

		self.__ydm_sync_status = Gtk.MenuItem(label="")
		self.__menu.append(self.__ydm_sync_status)

		self.__menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_quota = Gtk.MenuItem(label="Quota")
		self.__menu.append(self.__ydm_quota)
		self.__ydm_quota_sub = Gtk.Menu()
		mi = Gtk.MenuItem(label="Path to Yandex Disk folder:")
		self.__ydm_quota_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_quota_sub_path = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_path.connect("activate", self.on_ydpath_activate)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_path)
		self.__ydm_quota_sub.append(Gtk.SeparatorMenuItem.new())
		self.__ydm_quota_sub_total = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_total.set_sensitive(False)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_total)
		self.__ydm_quota_sub_used = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_used.set_sensitive(False)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_used)
		self.__ydm_quota_sub_available = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_available.set_sensitive(False)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_available)
		self.__ydm_quota_sub_maxfile = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_maxfile.set_sensitive(False)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_maxfile)
		self.__ydm_quota_sub_trash = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_trash.set_sensitive(False)
		self.__ydm_quota_sub.append(self.__ydm_quota_sub_trash)
		self.__ydm_quota.set_submenu(self.__ydm_quota_sub)

		self.__ydm_rsynced = Gtk.MenuItem(label="Recently synced")
		self.__menu.append(self.__ydm_rsynced)
		self.__ydm_rsynced_sub = Gtk.Menu()
		mi = Gtk.MenuItem(label="Recently synced files:")
		self.__ydm_rsynced_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_rsynced_sub_files = Gtk.MenuItem(label="(none)")
		self.__ydm_rsynced_sub_files.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_files)
		mi = Gtk.MenuItem(label="Recently synced folders:")
		self.__ydm_rsynced_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_rsynced_sub_dirs = Gtk.MenuItem(label="(none)")
		self.__ydm_rsynced_sub_dirs.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_dirs)
		self.__ydm_rsynced.set_submenu(self.__ydm_rsynced_sub)

		self.__menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_start_stop = Gtk.MenuItem(label="Start/Stop")
		self.__ydm_start_stop.connect("activate", self.start_stop)
		self.__menu.append(self.__ydm_start_stop)

		self.__ydm_preferences = Gtk.MenuItem(label="Preferences...")
		self.__menu.append(self.__ydm_preferences)

		self.__menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_about = Gtk.MenuItem(label="About...")
		self.__menu.append(self.__ydm_about)

		self.__ydm_quit = Gtk.MenuItem(label="Exit")
		self.__ydm_quit.connect("activate", self.quit)
		self.__menu.append(self.__ydm_quit)

		# Connect yandex-disk CLI and start getting regular status updates
		if disk is None:
			raise NoYDCLI
		self.__disk = disk
		self.monitor(UPDATE_INTERVAL)

		self.__menu.show_all()
		Gtk.main()
		return
	
	def __del__(self):
		self.desist()

	def __theme_name_changed(self, settings, gparam):
		cwd = os.getcwd()
		theme = settings.get_property("gtk-theme-name")
		if theme.find("dark") < 0 and theme.find("Dark") < 0:
			# Light theme
			self.__indicator.set_icon_theme_path(cwd + "/Icons/Light_Theme")
		else:
			# Dark theme
			self.__indicator.set_icon_theme_path(cwd + "/Icons/Dark_Theme")
	
	def on_ydpath_activate(self, source):
		run(["nautilus", self.__disk.get_yd_path()])
	
	def start_stop(self, source):
		match self.__ydm_start_stop.get_label():
			case "Start \u23F5\uFE0E":
				self.__disk.command("start")
			case "Stop \u23F9\uFE0E":
				self.__disk.command("stop")

	def quit(self, source):
		Gtk.main_quit()

	def monitor(self, interval:float):
		# Start updating yandex-disk status at regular intervals (in seconds).
		# Use desist() to stop.
		if not self.__monitoring:
			self.__monitoring = True
			self.__daemon = Thread(target=self.__updateWorker, args=(interval,), daemon=True)
			self.__daemon.start()

	def desist(self):
		# Stop updating yandex-disk status.
		self.__monitoring = False

	def __updateWorker(self, interval:float):
		while self.__monitoring:
			self.__disk.command("status")
			sync_status = self.__disk.get_sync_status()
			old_icon = self.__indicator.get_icon()
			old_action = self.__ydm_start_stop.get_label()
			new_action = "Stop \u23F9\uFE0E"
			match sync_status:
				case "idle": 
					new_icon = "YDNormal.png"
				case "busy": 
					new_icon = "YDSync.png"
				case "index": 
					new_icon = "YDSync.png"
				case "paused": 
					new_icon = "YDPaused.png"
				case "error": 
					new_icon = "YDError.png"
				case _: 
					new_icon = "YDDisconnect.png"
					new_action = "Start \u23F5\uFE0E"
					sync_status = "not running"
			if old_icon != new_icon:
				self.__indicator.set_icon(new_icon)
			if old_action != new_action:
				self.__ydm_start_stop.set_label(new_action)

			sync_prog = self.__disk.get_sync_prog()
			if sync_prog != "":
				sync_status += "\n" + sync_prog
			self.__ydm_sync_status.set_label("Status: " + sync_status)

			l = self.__disk.get_yd_path()
			if l != self.__ydm_quota_sub_path.get_label():
				self.__ydm_quota_sub_path.set_label(l)

			l = "Total: " + self.__disk.get_yd_total()
			if l != self.__ydm_quota_sub_total.get_label():
				self.__ydm_quota_sub_total.set_label(l)
			l = "Used: " + self.__disk.get_yd_used()
			if l != self.__ydm_quota_sub_used.get_label():
				self.__ydm_quota_sub_used.set_label(l)
			l = "Available: " + self.__disk.get_yd_available()
			if l != self.__ydm_quota_sub_available.get_label():
				self.__ydm_quota_sub_available.set_label(l)
			l = "Max file: " + self.__disk.get_yd_maxfile()
			if l != self.__ydm_quota_sub_maxfile.get_label():
				self.__ydm_quota_sub_maxfile.set_label(l)
			l = "Trash: " + self.__disk.get_yd_trash()
			if l != self.__ydm_quota_sub_trash.get_label():
				self.__ydm_quota_sub_trash.set_label(l)

			nf = []
			for f in self.__disk.get_yd_lastfiles():
				if len(f) > 49:
					f = f[0:21] + " ... " + f[-22:]
				nf.append(f)
			nfstr = '\n'.join(nf)
			if nfstr == "":
				nfstr = "(none)"
			if nfstr != self.__ydm_rsynced_sub_files.get_label():
				self.__ydm_rsynced_sub_files.set_label(nfstr)

			nf = []
			for f in self.__disk.get_yd_lastdirs():
				if len(f) > 49:
					f = f[0:21] + " ... " + f[-22:]
				nf.append(f)
			nfstr = '\n'.join(nf)
			if nfstr == "":
				nfstr = "(none)"
			if nfstr != self.__ydm_rsynced_sub_dirs.get_label():
				self.__ydm_rsynced_sub_dirs.set_label(nfstr)

			sleep(interval)


