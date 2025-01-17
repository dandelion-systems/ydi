# -*- coding: utf-8 -*-

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
from subprocess import check_output, getoutput, CalledProcessError
import os
import json
import locale
import gettext

from yd_cli import YandexDisk, NoYDCLI


# Translation -----------------------------------------------
#

# Get user interface language
locale.setlocale(locale.LC_ALL, "")
message_language = locale.getlocale(locale.LC_MESSAGES)[0][0:2] 

# Install the corresponding translation
lang = gettext.translation(
	domain="messages", 
	localedir="locales", 
	fallback=True, # fall back to "en" in case some locale other 
	               # than en/ru/fr is active
	languages=[message_language])
lang.install()
_ = lang.gettext # This is not necessary as lang.install() gets `_` defined, 
                 # but vscode complains much too much w/o this line :-)


# Debug helper logger ---------------------------------------
#
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

class YDISettings:

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



# Application menu ------------------------------------------
#
class YDIMenu(Gtk.Menu):
	__settings:YDISettings = None

	__ydm_sync_status = None
	
	__ydm_quota_sub_path = None
	__ydm_quota_sub_total = None
	__ydm_quota_sub_used = None
	__ydm_quota_sub_available = None
	__ydm_quota_sub_maxfile = None
	__ydm_quota_sub_trash = None
	
	__ydm_rsynced_sub_files = None
	__ydm_rsynced_sub_dirs = None
	__ydm_rsynced_sub = None

	__ydm_start_stop = None

	def __init__(self, ydisettings:YDISettings, menu_actions:dict):
		super().__init__()
		self.__settings = ydisettings
		self.__make_menu(menu_actions)

	def __make_menu(self, ma:dict):
		self.__ydm_sync_status = Gtk.MenuItem(label="")
		self.append(self.__ydm_sync_status)

		self.append(Gtk.SeparatorMenuItem.new())

		quota = Gtk.MenuItem(label=_("Quota"))
		self.append(quota)
		quota_sub = Gtk.Menu()
		quota.set_submenu(quota_sub)

		mi = Gtk.MenuItem(label=_("Path to Yandex Disk folder:"))
		mi.set_sensitive(False)
		quota_sub.append(mi)

		self.__ydm_quota_sub_path = Gtk.MenuItem(label="")
		self.__ydm_quota_sub_path.connect("activate", ma["on_ydpath"])
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

		rsynced = Gtk.MenuItem(label=_("Recently synced"))
		self.append(rsynced)
		self.__ydm_rsynced_sub = Gtk.Menu()
		rsynced.set_submenu(self.__ydm_rsynced_sub)

		mi = Gtk.MenuItem(label=_("Recently synced files:"))
		mi.tag = "@m_recent_files"
		self.__ydm_rsynced_sub.append(mi)
		mi.set_sensitive(False)

		self.__ydm_rsynced_sub_files = Gtk.MenuItem(label=_("  (none)"))
		self.__ydm_rsynced_sub_files.tag = "@f"
		self.__ydm_rsynced_sub_files.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_files)

		mi = Gtk.MenuItem(label=_("Recently synced folders:"))
		mi.tag = "@m_recent_folders"
		self.__ydm_rsynced_sub.append(mi)
		mi.set_sensitive(False)

		self.__ydm_rsynced_sub_dirs = Gtk.MenuItem(label=_("  (none)"))
		self.__ydm_rsynced_sub_dirs.tag = "@d"
		self.__ydm_rsynced_sub_dirs.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_dirs)

		self.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_start_stop = Gtk.MenuItem(label=_("Start/Stop"))
		self.__ydm_start_stop.connect("activate", ma["on_start_stop"])
		self.append(self.__ydm_start_stop)

		preferences = Gtk.MenuItem(label=_("Preferences"))
		self.append(preferences)
		preferences_sub = Gtk.Menu()
		preferences.set_submenu(preferences_sub)

		mi = Gtk.MenuItem(label=_("Update frequency:"))
		preferences_sub.append(mi)
		mi.set_sensitive(False)

		preferences_sub_power = Gtk.RadioMenuItem.new_with_label(group=None, label=_("Power saver"))
		preferences_sub.append(preferences_sub_power)
		preferences_sub_power.set_draw_as_radio(False)
		preferences_sub_power.connect("activate", ma["on_power_saver"])
		group = preferences_sub_power.get_group()

		preferences_sub_medium = Gtk.RadioMenuItem.new_with_label(group=group, label=_("Medium"))
		preferences_sub.append(preferences_sub_medium)
		preferences_sub_medium.set_draw_as_radio(False)
		preferences_sub_medium.connect("activate", ma["on_medium"])

		preferences_sub_high = Gtk.RadioMenuItem.new_with_label(group=group, label=_("High"))
		preferences_sub.append(preferences_sub_high)
		preferences_sub_high.set_draw_as_radio(False)
		preferences_sub_high.connect("activate", ma["on_high"])

		match self.__settings.get_frequency():
			case "power_saver":
				preferences_sub_power.set_active(True)
			case "medium":
				preferences_sub_medium.set_active(True)
			case "high":
				preferences_sub_high.set_active(True)

		mi = Gtk.MenuItem(label=_("Icon theme:"))
		preferences_sub.append(mi)
		mi.set_sensitive(False)

		preferences_sub_themed = Gtk.RadioMenuItem.new_with_label(group=None, label=_("Follow desktop theme"))
		preferences_sub.append(preferences_sub_themed)
		preferences_sub_themed.set_draw_as_radio(False)
		preferences_sub_themed.connect("activate", ma["on_themed"])
		group = preferences_sub_themed.get_group()

		preferences_sub_white = Gtk.RadioMenuItem.new_with_label(group=group, label=_("Always white"))
		preferences_sub.append(preferences_sub_white)
		preferences_sub_white.set_draw_as_radio(False)
		preferences_sub_white.connect("activate", ma["on_white"])

		preferences_sub_black = Gtk.RadioMenuItem.new_with_label(group=group, label=_("Always black"))
		preferences_sub.append(preferences_sub_black)
		preferences_sub_black.set_draw_as_radio(False)
		preferences_sub_black.connect("activate", ma["on_black"])

		match self.__settings.get_icon_theme():
			case "themed":
				preferences_sub_themed.set_active(True)
			case "white":
				preferences_sub_white.set_active(True)
			case "black":
				preferences_sub_black.set_active(True)

		self.append(Gtk.SeparatorMenuItem.new())

		mi = Gtk.MenuItem(label=_("About"))
		mi.connect("activate", ma["on_about"])
		self.append(mi)

		mi = Gtk.MenuItem(label=_("Exit"))
		mi.connect("activate", ma["on_quit"])
		self.append(mi)

	def get_label(self, item:str):
		match item:
			case "start_stop":
				return self.__ydm_start_stop.get_label()
			case "sync_status":
				return self.__ydm_sync_status.get_label()
			case "path":
				return self.__ydm_quota_sub_path.get_label()
			case "total":
				return self.__ydm_quota_sub_total.get_label()
			case "used":
				return self.__ydm_quota_sub_used.get_label()
			case "available":
				return self.__ydm_quota_sub_available.get_label()
			case "maxfile":
				return self.__ydm_quota_sub_maxfile.get_label()
			case "trash":
				return self.__ydm_quota_sub_trash.get_label()

	def set_label(self, item:str, label:str):
		match item:
			case "start_stop":
				self.__ydm_start_stop.set_label(label)
			case "sync_status":
				self.__ydm_sync_status.set_label(label)
			case "path":
				self.__ydm_quota_sub_path.set_label(label)
			case "total":
				self.__ydm_quota_sub_total.set_label(label)
			case "used":
				self.__ydm_quota_sub_used.set_label(label)
			case "available":
				self.__ydm_quota_sub_available.set_label(label)
			case "maxfile":
				self.__ydm_quota_sub_maxfile.set_label(label)
			case "trash":
				self.__ydm_quota_sub_trash.set_label(label)

	def get_rsynced_submenu(self):
		return self.__ydm_rsynced_sub
	
	def get_rsynced(self, tag_to_search:str):
		tagged_items = []
		for mi in self.__ydm_rsynced_sub.get_children():
			l = len(mi.tag)
			if mi.tag.find(tag_to_search) == 0 and l > 2: # All MenuItems here MUST have a tag
				tagged_items.append(mi.tag[2:l])
		return tagged_items



# Main application ------------------------------------------
#

# Menu labels with Unicode 'play' and 'stop' symbols
START_LABEL = _("Start ⏵")
STOP_LABEL = _("Stop ⏹")

# yandex-disk status monitor update interval in seconds
UPDATE_INTERVAL_PS = 5
UPDATE_INTERVAL_MD = 2
UPDATE_INTERVAL_HG = 1

class YDIndicator:
	# yandex-disk CLI interface
	__disk:YandexDisk = None
	
	# AppIndicator instance
	__indicator:AppIndicator = None

	# Gtk AppIndicator menu. Menu items below will change content 
	# dynamically to reflect the status of syncing
	__menu:YDIMenu = None

	# Status updater thread
	__updater = None

	# Status updater run flag (simple semaphore)
	__monitoring = False

	# Settings
	__settings:YDISettings = None


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
			self.__settings = YDISettings(cfg_file)
		except YDInvalidSettings:
			pass

		# YD status indicator and control
		self.__indicator = AppIndicator.Indicator.new(
			APPINDICATOR_ID, "YDNormal.png", 
			AppIndicator.IndicatorCategory.SYSTEM_SERVICES
			)
		self.__indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

		# YD control menu
		menu_actions = {
			"on_ydpath": self.on_ydpath,
			"on_start_stop": self.on_start_stop,
			"on_power_saver": self.on_power_saver,
			"on_medium": self.on_medium,
			"on_high": self.on_high,
			"on_themed": self.on_themed,
			"on_white": self.on_white,
			"on_black": self.on_black,
			"on_about": self.on_about,
			"on_quit": self.on_quit
		}

		self.__menu = YDIMenu(
			ydisettings=self.__settings, 
			menu_actions=menu_actions
			)
		self.__indicator.set_menu(self.__menu)
		self.__menu.show_all()

		# YD themed icons
		Gtk.Settings.get_default().connect(
			"notify::gtk-theme-name", 
			self.on_theme_name_changed
			)
		self.on_theme_name_changed(Gtk.Settings.get_default(), None)

		# Start getting regular status updates
		self.monitor()

		Gtk.main()	
	
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
		iconpath = self.get_icon_path()
		match self.__settings.get_icon_theme():
			case "themed":
				theme = settings.get_property("gtk-theme-name")
				if theme.find("dark") < 0 and theme.find("Dark") < 0:
					# Light theme
					iconpath = os.path.join(iconpath, "Light_Theme")
					
				else:
					# Dark theme
					iconpath = os.path.join(iconpath, "Dark_Theme")
					
			case "white":
				# `Always white` icons theme
				iconpath = os.path.join(iconpath, "Dark_Theme")
				
			case "black":
				# `Always black` icons theme
				iconpath = os.path.join(iconpath, "Light_Theme")
				
			case _:
				return

		GLib.idle_add(
			self.__indicator.set_icon_theme_path,
			iconpath
		)
	
	def on_ydpath(self, source):
		self.__open_fm(self.__disk.get_yd_path())
	
	def on_start_stop(self, source):
		self.desist()
		if self.__menu.get_label("start_stop") == START_LABEL:
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
			text=_("Yandex Disk Indicator"),
			)
		dialog.format_secondary_text(
			_("Yandex Disk indicator and control\nversion 1.1\n© 2025 Dandelion {Systems}\n\n") + yd_version
			)
		dialog.run()
		dialog.destroy()

	def on_quit(self, source):
		self.desist()
		remove_pid_file()
		Gtk.main_quit()

	def get_icon_path(self):
		loclist = getoutput("dpkg -L dandelion-ydi | grep Icons")
		try:
			(iconpath,_) = loclist.splitlines()[0].split(sep="Icons") + "Icons" # /
		except:
			iconpath = os.path.join(os.getcwd(), "Icons") # the default is "/opt/dandelion.systems/ydi/Icons/"
		return iconpath

	def monitor(self):
		match self.__settings.get_frequency():
			case "power_saver":
				interval = UPDATE_INTERVAL_PS
			case "medium":
				interval = UPDATE_INTERVAL_MD
			case "high":
				interval = UPDATE_INTERVAL_HG
			case _: # just a precaution
				interval = UPDATE_INTERVAL_MD

		# Start updating yandex-disk status at regular intervals (in seconds).
		# Use desist() to stop
		if not self.__monitoring:
			self.__monitoring = True
			self.__updater = Thread(
				target=self.__update_worker, 
				args=(interval,)
			)
			self.__updater.start()

	def desist(self):
		# Stop updating yandex-disk status
		self.__monitoring = False
		self.__updater.join()

	def on_rcfile(self, source):
		yd_path = self.__disk.get_yd_path()
		file_folder = os.path.dirname(source.tag[2:len(source.tag)])
		self.__open_fm(os.path.join(yd_path, file_folder))

	def on_rcfolder(self, source):
		yd_path = self.__disk.get_yd_path()
		self.__open_fm(
			os.path.join(yd_path, source.tag[2:len(source.tag)])
		)

	def __open_fm(self, dir_path:str):
		fm = which("nautilus")
		if fm is None:
			fm = which("thunar")
		if fm is None:
			fm = which("pcmanfm")
		if fm is not None:
			run([fm, dir_path])
		else:
			dialog = Gtk.MessageDialog(
				flags=0,
				message_type=Gtk.MessageType.WARNING,
				buttons=Gtk.ButtonsType.OK,
				text=_("File Manager not found"),
				)
			dialog.format_secondary_text(
				_("Nautilus, Thunar and PCManFM file managers are suported, none found")
				)
			dialog.run()
			dialog.destroy()

	def __do_updates(self, updates:dict):
		def make_mi_label(s:str, l:int=37):
			if len(s) > l:
				s = "  " + s[0:int((l-7)/2)] + " ... " + s[-int((l-7)/2):]
			else:
				s = "  " + s
			return s
		
		for what in updates:
			match what:
				case "icon":
					self.__indicator.set_icon(updates[what])

				case ("sync_status" | "path" | "total" | "used" |
				      "available" | "maxfile" | "trash" | "start_stop"):
					self.__menu.set_label(what, updates[what])

				case ("rfiles" | "rdirs"):
					# Sanity check
					value = updates[what]
					if not isinstance(value, list):
						raise ValueError
					
					# Are we updating the list of files or folders?
					tag_to_search = (
						lambda x: {True:"@f", False:"@d"}[x=="rfiles"]
						)(what)

					# The submenu to update
					rsynced_submenu = self.__menu.get_rsynced_submenu()
					
					# Destroy all the recent files or folders listed on the menu
					# These ones will have a tag starting with `@f` or `@d` followed 
					# by a file or folder path relative to the Yandex Disk folder
					for mi in rsynced_submenu.get_children():
						if mi.tag.find(tag_to_search) == 0:
							mi.destroy()

					# Determine the staring position where 
					# the new list will be inserted to	
					pos = 0
					rfiles_start_pos = 0
					rdirs_start_pos = 0
					for mi in rsynced_submenu.get_children():
						if mi.tag == "@m_recent_files":
							rfiles_start_pos = pos + 1
						elif mi.tag == "@m_recent_folders":
							rdirs_start_pos = pos + 1
						pos = pos + 1

					# We will insert/update the menu items with recent 
					# files or folders staring from `pos` as position pos-1 is 
					# occupied by `Recently synced files/folders:` menu item
					pos = (
						lambda x: {True:rfiles_start_pos, False:rdirs_start_pos}[x=="rfiles"]
						)(what)
					starting_pos = pos

					# This will be the function triggered at menuitem activation 
					activation_funct = (
						lambda x: {True:self.on_rcfile, False:self.on_rcfolder}[x=="rfiles"]
						)(what)

					# Update menu items
					for name_on_list in value:
						mi = Gtk.MenuItem(label=make_mi_label(name_on_list))
						mi.tag = tag_to_search + name_on_list
						mi.connect("activate", activation_funct)
						rsynced_submenu.insert(mi, pos)
						pos = pos + 1

					# Finally: if pos is still at `starting_pos`, 
					# the `value` list was empty and we need 
					# to create a `  (none)` item
					if pos == starting_pos:
						none_item = Gtk.MenuItem(label=_("  (none)"))
						none_item.tag = tag_to_search
						none_item.set_sensitive(False)
						rsynced_submenu.insert(none_item, starting_pos)
		
					# Update the visual representation of the menu
					rsynced_submenu.show_all()

		return False

	def __update_worker(self, interval:float):
		while self.__monitoring:
			update_actions = {}
			
			old_icon        = self.__indicator.get_icon()
			old_start_stop  = self.__menu.get_label("start_stop")
			old_sync_status = self.__menu.get_label("sync_status")
			old_path        = self.__menu.get_label("path")
			old_total       = self.__menu.get_label("total")
			old_used        = self.__menu.get_label("used")
			old_available   = self.__menu.get_label("available")
			old_maxfile     = self.__menu.get_label("maxfile")
			old_trash       = self.__menu.get_label("trash")
			old_files       = self.__menu.get_rsynced("@f")
			old_dirs        = self.__menu.get_rsynced("@d")

			self.__disk.command("status")
			new_sync_status = self.__disk.get_sync_status()
			
			match new_sync_status:
				case "idle": 
					new_icon = "YDNormal.png"
					new_start_stop  = STOP_LABEL
					new_sync_status = _("idle")
				case "busy": 
					new_icon = "YDSync.png"
					new_start_stop  = STOP_LABEL
					new_sync_status = _("busy")
				case "index": 
					new_icon = "YDSync.png"
					new_start_stop  = STOP_LABEL
					new_sync_status = _("index")
				case "paused": 
					new_icon = "YDPaused.png"
					new_start_stop  = STOP_LABEL
					new_sync_status = _("paused")
				case "error": 
					new_icon = "YDError.png"
					new_start_stop  = STOP_LABEL
					new_sync_status = _("error")
				case _: # either stopped or in `no internet access` state
					new_icon = "YDDisconnect.png"
					new_start_stop = START_LABEL
					new_sync_status = _("not running")
			
			if old_icon != new_icon:
				update_actions["icon"] = new_icon
				
			if old_start_stop != new_start_stop:
				update_actions["start_stop"] = new_start_stop

			l = self.__disk.get_sync_prog()
			if l != "":
				new_sync_status += "\n" + l
			new_sync_status = _("Status: ") + new_sync_status
			if new_sync_status != old_sync_status:
				update_actions["sync_status"] = new_sync_status

			l = self.__disk.get_yd_path()
			if l != old_path:
				update_actions["path"] = l

			l = _("Total: ") + self.__disk.get_yd_total()
			if l != old_total:
				update_actions["total"] = l
				
			l = _("Used: ") + self.__disk.get_yd_used()
			if l != old_used:
				update_actions["used"] = l
				
			l = _("Available: ") + self.__disk.get_yd_available()
			if l != old_available:
				update_actions["available"] = l
				
			l = _("Max file: ") + self.__disk.get_yd_maxfile()
			if l != old_maxfile:
				update_actions["maxfile"] = l
				
			l = _("Trash: ") + self.__disk.get_yd_trash()
			if l != old_trash:
				update_actions["trash"] = l

			new_files = self.__disk.get_yd_lastfiles()
			if new_files != old_files:
				update_actions["rfiles"] = new_files

			new_dirs = self.__disk.get_yd_lastdirs()
			if new_dirs != old_dirs:
				update_actions["rdirs"] = new_dirs

			if update_actions != {}:
				GLib.idle_add(
					self.__do_updates,
					update_actions,
					priority=GLib.PRIORITY_HIGH
				)

			sleep(interval)
