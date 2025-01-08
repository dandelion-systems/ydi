"""
	This file is part of Yandex Disk indicator and control (YDI).

	Copyright 2025 Dandelion Systems <dandelion.systems@gmail.com>

	YDI is free software; you can redistribute it and/or modify
	it under the terms of the MIT License.

	YDI is distributed in the hope that it will be useful, but
	WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. 
	See the MIT License for more details.

	SPDX-License-Identifier: MIT
"""

from gi import require_version

require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository import GLib

try:
	require_version("AppIndicator3", "0.1")
	from gi.repository import AppIndicator3 as AppIndicator
except Exception:
	require_version("AyatanaAppIndicator3", "0.1")
	from gi.repository import AyatanaAppIndicator3 as AppIndicator

from subprocess import run
from threading import Thread
from time import sleep
from shutil import which
from subprocess import check_output, CalledProcessError
import os
import json

from yd_cli import YandexDisk, NoYDCLI

# Debug helper logger
def log(msg:str, do:bool=False):
	if do:
		from datetime import datetime
		now = datetime.now()
		print(now.strftime("%H:%M:%S"), ": ", msg)


# PID file management ---------------------------------------
#
APPINDICATOR_ID = "com.dandelion-systems.yandexdisk"
PID_PATH = "/tmp/" + APPINDICATOR_ID
PID_FILE = PID_PATH + "/ydi.pid"

def create_pid_file():	
	open_flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY)
	open_mode = 0o644
	pidfile_fd = os.open(PID_FILE, open_flags, open_mode)
	pidfile = os.fdopen(pidfile_fd, "w")
	pidfile.write("%s\n" % os.getpid())
	pidfile.close()

def remove_pid_file():
	os.remove(PID_FILE)

def is_unique():
	try:
		# No directory
		if not os.path.exists(PID_PATH):
			os.mkdir(PID_PATH)
			
		# No PID file
		if not os.path.exists(PID_FILE):
			create_pid_file()
		
		# PID file exists, check if the process is still alive
		else:
			try:
				check_output(["pgrep", "-F", PID_FILE])
				# Exception has not occured, zero pgrep return code, 
				# that is, another ydi process is alive
				return False
			except CalledProcessError: 
				# Non-zero return code means this is a stale PID file,
				# recreate it with our PID
				remove_pid_file()
				create_pid_file()

		# Sure we are the unique ydi instance
		return True
	
	except: # OSError and others
		return False

# This exception is thrown if we try and launch a second
# instance of ydi
class YDINotUnique(Exception):
	pass



# Settings management ---------------------------------------
#

# This exception is thrown if we meet anything strange in
# the settings file
class YDInvalidSettings(Exception):
	pass

class Settings:

	__sfile = ""

	__settings = {
		"icon_theme": "themed",
		"frequency": "power_saver"
	}

	__valid_icon_theme = ["themed", "white", "black"]

	__valid_frequency = ["power_saver", "medium", "high"]

	def __init__(self, sfile:str):
		self.__sfile = sfile
		self.read_settings()
		pass

	def get_settings(self):
		return self.__settings
	
	def get_icon_theme(self):
		return self.__settings["icon_theme"]
	
	def get_frequency(self):
		return self.__settings["frequency"]
	
	def set_icon_theme(self, icon_theme:str):
		if icon_theme not in self.__valid_icon_theme:
			raise YDInvalidSettings
		self.__settings["icon_theme"] = icon_theme
		self.save_settings()
	
	def set_frequency(self, frequency:str):
		if frequency not in self.__valid_frequency:
			raise YDInvalidSettings
		self.__settings["frequency"] = frequency
		self.save_settings()

	def read_settings(self):
		# If the settings file cannot be read we sasify ourselves
		# with the defaults in self.__settings. This is the case 
		# of fresh installation for instance
		try:
			with open(self.__sfile, "r") as s:
				settings = json.load(s)
		except OSError:
			return

		if type(settings) is not dict:
			raise YDInvalidSettings
		
		if "icon_theme" not in settings or "frequency" not in settings:
			raise YDInvalidSettings
		
		if settings["icon_theme"] in self.__valid_icon_theme:
			self.__settings["icon_theme"] = settings["icon_theme"]
		else:
			raise YDInvalidSettings
		
		if settings["frequency"] in self.__valid_frequency:
			self.__settings["frequency"] = settings["frequency"]
		else:
			raise YDInvalidSettings
		
	def save_settings(self):
		# If settings cannot be saved (corrupt directory tree?),
		# it is not a big deal, so just return silently
		try:
			with open(self.__sfile, "w") as s:
				settings = json.dump(self.__settings, s)
		except OSError:
			return



# Main application ------------------------------------------
#

# Menu labels with Unicode 'play' and 'stop' symbols
START_LABEL = "Start \u23F5\uFE0E"
STOP_LABEL = "Stop \u23F9\uFE0E"

# yandex-disk status monitor update interval in seconds
UPDATE_INTERVAL_PS = 5
UPDATE_INTERVAL_MD = 2
UPDATE_INTERVAL_HG = 1

class YDIndicator:
	# yandex-disk CLI interface
	__disk = None
	
	# AppIndicator instance
	__indicator = None

	# Gtk AppIndicator menu. Menu items below will change content 
	# dynamically to reflect the status of syncing
	__ydm_sync_status = None
	
	__ydm_quota_sub_path = None
	__ydm_quota_sub_total = None
	__ydm_quota_sub_used = None
	__ydm_quota_sub_available = None
	__ydm_quota_sub_maxfile = None
	__ydm_quota_sub_trash = None
	
	__ydm_rsynced_sub_files = None
	__ydm_rsynced_sub_dirs = None

	__ydm_start_stop = None

	# Status updater thread
	__updater = None

	# Status updater run flag (simple semaphore)
	__monitoring = False

	# Settings
	__settings:Settings = None


	def __init__(self, disk:YandexDisk=None):
		# Enable multithreading in Gtk
		GLib.threads_init()

		# Check if we are running already
		if not is_unique():
			raise YDINotUnique
		
		# Connect yandex-disk CLI
		if disk is None:
			raise NoYDCLI
		self.__disk = disk

		# Read the settings
		# In case they are corrupt, we silently revert to defaults
		try:
			cfg_file = os.path.expanduser("~") + "/.config/yandex-disk/ydi.cfg"
			self.__settings = Settings(cfg_file)
		except YDInvalidSettings:
			pass

		# YD status indicator and control
		self.__indicator = AppIndicator.Indicator.new(
			APPINDICATOR_ID, "YDNormal.png", AppIndicator.IndicatorCategory.SYSTEM_SERVICES
			)
		self.__indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

		# YD themed icons
		Gtk.Settings.get_default().connect("notify::gtk-theme-name", self.on_theme_name_changed)
		self.on_theme_name_changed(Gtk.Settings.get_default(), None)

		# YD control menu
		self.__make_menu()

		# Start getting regular status updates
		self.monitor()

		Gtk.main()
		return
	
	def __make_menu(self):

		menu = Gtk.Menu()
		self.__indicator.set_menu(menu)

		self.__ydm_sync_status = Gtk.MenuItem(label="")
		menu.append(self.__ydm_sync_status)

		menu.append(Gtk.SeparatorMenuItem.new())

		quota = Gtk.MenuItem(label="Quota")
		menu.append(quota)
		quota_sub = Gtk.Menu()
		mi = Gtk.MenuItem(label="Path to Yandex Disk folder:")
		quota_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_quota_sub_path = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_path.connect("activate", self.on_ydpath_activate)
		quota_sub.append(self.__ydm_quota_sub_path)
		quota_sub.append(Gtk.SeparatorMenuItem.new())
		self.__ydm_quota_sub_total = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_total.set_sensitive(False)
		quota_sub.append(self.__ydm_quota_sub_total)
		self.__ydm_quota_sub_used = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_used.set_sensitive(False)
		quota_sub.append(self.__ydm_quota_sub_used)
		self.__ydm_quota_sub_available = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_available.set_sensitive(False)
		quota_sub.append(self.__ydm_quota_sub_available)
		self.__ydm_quota_sub_maxfile = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_maxfile.set_sensitive(False)
		quota_sub.append(self.__ydm_quota_sub_maxfile)
		self.__ydm_quota_sub_trash = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_trash.set_sensitive(False)
		quota_sub.append(self.__ydm_quota_sub_trash)
		quota.set_submenu(quota_sub)

		rsynced = Gtk.MenuItem(label="Recently synced")
		menu.append(rsynced)
		rsynced_sub = Gtk.Menu()
		mi = Gtk.MenuItem(label="Recently synced files:")
		rsynced_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_rsynced_sub_files = Gtk.MenuItem(label="  (none)")
		self.__ydm_rsynced_sub_files.set_sensitive(False)
		rsynced_sub.append(self.__ydm_rsynced_sub_files)
		mi = Gtk.MenuItem(label="Recently synced folders:")
		rsynced_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_rsynced_sub_dirs = Gtk.MenuItem(label="  (none)")
		self.__ydm_rsynced_sub_dirs.set_sensitive(False)
		rsynced_sub.append(self.__ydm_rsynced_sub_dirs)
		rsynced.set_submenu(rsynced_sub)

		menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_start_stop = Gtk.MenuItem(label="Start/Stop")
		self.__ydm_start_stop.connect("activate", self.on_start_stop)
		menu.append(self.__ydm_start_stop)

		preferences = Gtk.MenuItem(label="Preferences...")
		menu.append(preferences)
		preferences_sub = Gtk.Menu()

		mi = Gtk.MenuItem(label="Update frequency:")
		preferences_sub.append(mi)
		mi.set_sensitive(False)

		preferences_sub_power = Gtk.RadioMenuItem.new_with_label(group=None, label="Power saver")
		preferences_sub.append(preferences_sub_power)
		preferences_sub_power.set_draw_as_radio(False)
		preferences_sub_power.connect("activate", self.on_power_saver)
		group = preferences_sub_power.get_group()

		preferences_sub_medium = Gtk.RadioMenuItem.new_with_label(group=group, label="Medium")
		preferences_sub.append(preferences_sub_medium)
		preferences_sub_medium.set_draw_as_radio(False)
		preferences_sub_medium.connect("activate", self.on_medium)

		preferences_sub_high = Gtk.RadioMenuItem.new_with_label(group=group, label="High")
		preferences_sub.append(preferences_sub_high)
		preferences_sub_high.set_draw_as_radio(False)
		preferences_sub_high.connect("activate", self.on_high)

		match self.__settings.get_frequency():
			case "power_saver":
				preferences_sub_power.set_active(True)
			case "medium":
				preferences_sub_medium.set_active(True)
			case "high":
				preferences_sub_high.set_active(True)

		mi = Gtk.MenuItem(label="Icon theme:")
		preferences_sub.append(mi)
		mi.set_sensitive(False)

		preferences_sub_themed = Gtk.RadioMenuItem.new_with_label(group=None, label="Follow desktop theme")
		preferences_sub.append(preferences_sub_themed)
		preferences_sub_themed.set_draw_as_radio(False)
		preferences_sub_themed.connect("activate", self.on_themed)
		group = preferences_sub_themed.get_group()

		preferences_sub_white = Gtk.RadioMenuItem.new_with_label(group=group, label="Always white")
		preferences_sub.append(preferences_sub_white)
		preferences_sub_white.set_draw_as_radio(False)
		preferences_sub_white.connect("activate", self.on_white)

		preferences_sub_black = Gtk.RadioMenuItem.new_with_label(group=group, label="Always black")
		preferences_sub.append(preferences_sub_black)
		preferences_sub_black.set_draw_as_radio(False)
		preferences_sub_black.connect("activate", self.on_black)

		match self.__settings.get_icon_theme():
			case "themed":
				preferences_sub_themed.set_active(True)
			case "white":
				preferences_sub_white.set_active(True)
			case "black":
				preferences_sub_black.set_active(True)

		preferences.set_submenu(preferences_sub)

		menu.append(Gtk.SeparatorMenuItem.new())

		mi = Gtk.MenuItem(label="About")
		mi.connect("activate", self.on_about)
		menu.append(mi)

		mi = Gtk.MenuItem(label="Exit")
		mi.connect("activate", self.on_quit)
		menu.append(mi)

		menu.show_all()
	
	def on_power_saver(self, source):
		self.__settings.set_frequency("power_saver")
		self.__settings.save_settings()
		if self.__monitoring:
			self.desist()
			self.monitor()

	def on_medium(self, source):
		self.__settings.set_frequency("medium")
		self.__settings.save_settings()
		if self.__monitoring:
			self.desist()
			self.monitor()
	
	def on_high(self, source):
		self.__settings.set_frequency("high")
		self.__settings.save_settings()
		if self.__monitoring:
			self.desist()
			self.monitor()
	
	def on_themed(self, source):
		self.__settings.set_icon_theme("themed")
		self.__settings.save_settings()
		self.on_theme_name_changed(Gtk.Settings.get_default(), None)
	
	def on_white(self, source):
		self.__settings.set_icon_theme("white")
		self.__settings.save_settings()
		self.on_theme_name_changed(Gtk.Settings.get_default(), None)
	
	def on_black(self, source):
		self.__settings.set_icon_theme("black")
		self.__settings.save_settings()
		self.on_theme_name_changed(Gtk.Settings.get_default(), None)

	def on_theme_name_changed(self, settings, gparam):
		cwd = os.getcwd()
		match self.__settings.get_icon_theme():
			case "themed":
				theme = settings.get_property("gtk-theme-name")
				if theme.find("dark") < 0 and theme.find("Dark") < 0:
					# Light theme
					self.__indicator.set_icon_theme_path(cwd + "/Icons/Light_Theme")
				else:
					# Dark theme
					self.__indicator.set_icon_theme_path(cwd + "/Icons/Dark_Theme")
			case "white":
				self.__indicator.set_icon_theme_path(cwd + "/Icons/Dark_Theme")
			case "black":
				self.__indicator.set_icon_theme_path(cwd + "/Icons/Light_Theme")
	
	def on_ydpath_activate(self, source):
		fm = which("nautilus")
		if fm is None:
			fm = which("thunar")
		if fm is None:
			fm = which("pcmanfm")
		if fm is not None:
			run([fm, self.__disk.get_yd_path()])
		else:
			dialog = Gtk.MessageDialog(
				flags=0,
				message_type=Gtk.MessageType.WARNING,
				buttons=Gtk.ButtonsType.OK,
				text="File Manager not found",
				)
			dialog.format_secondary_text(
				"Nautilus, Thunar and PCmanFM file managers are suported, none found"
				)
			dialog.run()
			dialog.destroy()
	
	def on_start_stop(self, source):
		self.desist()
		if self.__ydm_start_stop.get_label() == START_LABEL:
			self.__disk.command("start")
		else: # STOP_LABEL
			self.__disk.command("stop")
		self.monitor()

	def on_about(self, source):
		yd_version = self.__disk.command("-v")
		dialog = Gtk.MessageDialog(
			flags=0,
			message_type=Gtk.MessageType.INFO,
			buttons=Gtk.ButtonsType.OK,
			text="Yandex Disk Indicator",
			)
		dialog.format_secondary_text(
			"Yandex Disk indicator and control\nversion 1.0\n© 2025 Dandelion {Systems}\n\n" + yd_version
			)
		dialog.run()
		dialog.destroy()

	def on_quit(self, source):
		self.desist()
		remove_pid_file()
		Gtk.main_quit()

	def monitor(self):
		match self.__settings.get_frequency():
			case "power_saver":
				interval = UPDATE_INTERVAL_PS
			case "medium":
				interval = UPDATE_INTERVAL_MD
			case "high":
				interval = UPDATE_INTERVAL_HG
			case _: # just a precaution
				interval = UPDATE_INTERVAL_PS

		# Start updating yandex-disk status at regular intervals (in seconds).
		# Use desist() to stop
		if not self.__monitoring:
			self.__monitoring = True
			self.__updater = Thread(target=self.__update_worker, args=(interval,))
			self.__updater.start()

	def desist(self):
		# Stop updating yandex-disk status
		self.__monitoring = False
		self.__updater.join()

	def set_property(self, what:str, value):
		match what:
			case "icon":
				funct = self.__indicator.set_icon
			case "status":
				funct = self.__ydm_sync_status.set_label
			case "path":
				funct = self.__ydm_quota_sub_path.set_label
			case "total":
				funct = self.__ydm_quota_sub_total.set_label
			case "used":
				funct = self.__ydm_quota_sub_used.set_label
			case "available":
				funct = self.__ydm_quota_sub_available.set_label
			case "maxfile":
				funct = self.__ydm_quota_sub_maxfile.set_label
			case "trash":
				funct = self.__ydm_quota_sub_trash.set_label
			case "rfiles":
				funct = self.__ydm_rsynced_sub_files.set_label
			case "rdirs":
				funct = self.__ydm_rsynced_sub_dirs.set_label
			case "action":
				funct = self.__ydm_start_stop.set_label
			case _:
				return
		
		GLib.idle_add(funct, value, priority=GLib.PRIORITY_LOW)

	def __update_worker(self, interval:float):
		log("Update interval is {:.2f} seconds\n".format(interval))
		while self.__monitoring:
			self.__disk.command("status")
			
			sync_status = self.__disk.get_sync_status()
			old_icon    = self.__indicator.get_icon()
			old_action  = self.__ydm_start_stop.get_label()
			new_action  = STOP_LABEL
			
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
					new_action = START_LABEL
					sync_status = "not running"
			
			if old_icon != new_icon:
				self.set_property("icon", new_icon)
				
			if old_action != new_action:
				self.set_property("action", new_action)

			sync_prog = self.__disk.get_sync_prog()
			if sync_prog != "":
				sync_status += "\n" + sync_prog
			sync_status = "Status: " + sync_status
			if sync_status != self.__ydm_sync_status.get_label():
				self.set_property("status", sync_status)

			l = self.__disk.get_yd_path()
			if l != self.__ydm_quota_sub_path.get_label():
				self.set_property("path", l)

			l = "Total: " + self.__disk.get_yd_total()
			if l != self.__ydm_quota_sub_total.get_label():
				self.set_property("total", l)
				
			l = "Used: " + self.__disk.get_yd_used()
			if l != self.__ydm_quota_sub_used.get_label():
				self.set_property("used", l)
				
			l = "Available: " + self.__disk.get_yd_available()
			if l != self.__ydm_quota_sub_available.get_label():
				self.set_property("available", l)
				
			l = "Max file: " + self.__disk.get_yd_maxfile()
			if l != self.__ydm_quota_sub_maxfile.get_label():
				self.set_property("maxfile", l)
				
			l = "Trash: " + self.__disk.get_yd_trash()
			if l != self.__ydm_quota_sub_trash.get_label():
				self.set_property("trash", l)

			nf = []
			for f in self.__disk.get_yd_lastfiles():
				if len(f) > 47:
					f = "  " + f[0:20] + " ... " + f[-20:]
				else:
					f = "  " + f
				nf.append(f)
			nfstr = "\n".join(nf)
			if nfstr == "":
				nfstr = "  (none)"
			if nfstr != self.__ydm_rsynced_sub_files.get_label():
				self.set_property("rfiles", nfstr)

			nf = []
			for f in self.__disk.get_yd_lastdirs():
				if len(f) > 47:
					f = "  " + f[0:20] + " ... " + f[-20:]
				else:
					f = "  " + f
				nf.append(f)
			nfstr = "\n".join(nf)
			if nfstr == "":
				nfstr = "  (none)"
			if nfstr != self.__ydm_rsynced_sub_dirs.get_label():
				self.set_property("rdirs", nfstr)

			sleep(interval)


