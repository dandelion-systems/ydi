from gi import require_version

require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import GLib

try:
	require_version('AppIndicator3', '0.1')
	from gi.repository import AppIndicator3 as AppIndicator
except Exception:
	require_version('AyatanaAppIndicator3', '0.1')
	from gi.repository import AyatanaAppIndicator3 as AppIndicator

from subprocess import run
from threading import Thread
from time import sleep
from shutil import which
from subprocess import check_output, CalledProcessError
import os

from yd_cli import YandexDisk, NoYDCLI

# yandex-disk status monitor update interval in seconds
UPDATE_INTERVAL = 2

APPINDICATOR_ID = 'com.dandelion-systems.yandexdisk'
PID_PATH = "/tmp/" + APPINDICATOR_ID
PID_FILE = PID_PATH + "/ydi.pid"

START_LABEL = "Start \u23F5\uFE0E"
STOP_LABEL = "Stop \u23F9\uFE0E"

def log(msg:str, do:bool=False):
	if do:
		from datetime import datetime
		now = datetime.now()
		print(now.strftime("%H:%M:%S"), ": ", msg)

def create_pid_file():	
	open_flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY)
	open_mode = 0o644
	pidfile_fd = os.open(PID_FILE, open_flags, open_mode)
	pidfile = os.fdopen(pidfile_fd, 'w')
	pidfile.write("%s\n" % os.getpid())
	pidfile.close()

def remove_pid_file():
	os.remove(PID_FILE)

# Check if we are the only ydi instance
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

# Main application 
class YDIndicator:
	# yandex-disk CLI interface
	__disk = None
	
	# AppIndicator instance
	__indicator = None

	# Gtk AppIndicator menu. Some menu items will change dynamically to
	# reflect the status of syncing 
	__menu = None

	# Menu items
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

	# Status updater thread
	__updater = None

	# Status updater run flag (simple semaphore)
	__monitoring = False


	def __init__(self, disk:YandexDisk):
		# Enable multithreading in Gtk
		GLib.threads_init()

		# Check if we are running already
		if not is_unique():
			raise YDINotUnique

		# YD status indicator and control
		self.__indicator = AppIndicator.Indicator.new(
			APPINDICATOR_ID, "YDNormal.png", AppIndicator.IndicatorCategory.SYSTEM_SERVICES
			)
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
		self.__ydm_rsynced_sub_files = Gtk.MenuItem(label="  (none)")
		self.__ydm_rsynced_sub_files.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_files)
		mi = Gtk.MenuItem(label="Recently synced folders:")
		self.__ydm_rsynced_sub.append(mi)
		mi.set_sensitive(False)
		self.__ydm_rsynced_sub_dirs = Gtk.MenuItem(label="  (none)")
		self.__ydm_rsynced_sub_dirs.set_sensitive(False)
		self.__ydm_rsynced_sub.append(self.__ydm_rsynced_sub_dirs)
		self.__ydm_rsynced.set_submenu(self.__ydm_rsynced_sub)

		self.__menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_start_stop = Gtk.MenuItem(label="Start/Stop")
		self.__ydm_start_stop.connect("activate", self.on_start_stop)
		self.__menu.append(self.__ydm_start_stop)

		self.__ydm_preferences = Gtk.MenuItem(label="Preferences...")
		self.__menu.append(self.__ydm_preferences)

		self.__menu.append(Gtk.SeparatorMenuItem.new())

		self.__ydm_about = Gtk.MenuItem(label="About...")
		self.__ydm_about.connect("activate", self.on_about)
		self.__menu.append(self.__ydm_about)

		self.__ydm_quit = Gtk.MenuItem(label="Exit")
		self.__ydm_quit.connect("activate", self.on_quit)
		self.__menu.append(self.__ydm_quit)

		# Connect yandex-disk CLI
		if disk is None:
			raise NoYDCLI
		self.__disk = disk

		# Start getting regular status updates
		self.monitor(UPDATE_INTERVAL)

		self.__menu.show_all()
		Gtk.main()
		return

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
		self.monitor(UPDATE_INTERVAL)

	def on_about(self, source):
		yd_version = self.__disk.command("-v")
		dialog = Gtk.MessageDialog(
			flags=0,
			message_type=Gtk.MessageType.INFO,
			buttons=Gtk.ButtonsType.OK,
			text="Yandex Disk Indicator",
			)
		dialog.format_secondary_text(
			"Yandex Disk indicator and control\nby Dandelion {Systems}\nversion 1.0\n\n" + yd_version
			)
		dialog.run()
		dialog.destroy()

	def on_quit(self, source):
		self.desist()
		remove_pid_file()
		Gtk.main_quit()

	def monitor(self, interval:float):
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
			case "action":
				funct = self.__ydm_start_stop.set_label
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
			case _:
				return
		
		GLib.idle_add(funct, value, priority=GLib.PRIORITY_LOW)

	def __update_worker(self, interval:float):
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
			nfstr = '\n'.join(nf)
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
			nfstr = '\n'.join(nf)
			if nfstr == "":
				nfstr = "  (none)"
			if nfstr != self.__ydm_rsynced_sub_dirs.get_label():
				self.set_property("rdirs", nfstr)

			sleep(interval)


