from shutil import which
from subprocess import check_output, CalledProcessError

SYNC_PROG = 'Sync progress'
SYNC_STATUS = 'Synchronization core status'
YD_PATH = 'Path to Yandex.Disk directory'
YD_TOTAL = 'Total'
YD_USED = 'Used'
YD_AVAILABLE = 'Available'
YD_MAXFILE = 'Max file size'
YD_TRASH = 'Trash size'
YD_LASTFILES = 'file'
YD_LASTDIRS = 'directory'

class NoYDCLI(Exception):
	pass

class InvalidYDCmd(Exception):
	pass

class YandexDisk:
	# yandex-disk CLI instance as returned by which yandex-disk
	__cli = None

	# yandex-disk status details, e.g. sync core status, last synced files, etc.
	# Anything except 'idle', 'busy', 'index', 'paused' for SYNC_STATUS indicates an error.
	__status = {}

	def __init__(self):
		self.__cli = which("yandex-disk")
		if self.__cli is None:
			raise NoYDCLI
		return

	def get_sync_status(self):
		if SYNC_STATUS in self.__status:
			return self.__status[SYNC_STATUS]
		else:
			return ""

	def get_sync_prog(self):
		if SYNC_PROG in self.__status:
			return self.__status[SYNC_PROG]
		else:
			return ""

	def get_yd_path(self):
		if YD_PATH in self.__status:
			return self.__status[YD_PATH]
		else:
			return ""

	def get_yd_total(self):
		if YD_TOTAL in self.__status:
			return self.__status[YD_TOTAL]
		else:
			return ""

	def get_yd_used(self):
		if YD_USED in self.__status:
			return self.__status[YD_USED]
		else:
			return ""

	def get_yd_available(self):
		if YD_AVAILABLE in self.__status:
			return self.__status[YD_AVAILABLE]
		else:
			return ""

	def get_yd_maxfile(self):
		if YD_MAXFILE in self.__status:
			return self.__status[YD_MAXFILE]
		else:
			return ""

	def get_yd_trash(self):
		if YD_TRASH in self.__status:
			return self.__status[YD_TRASH]
		else:
			return ""

	def get_yd_lastfiles(self):
		if YD_LASTFILES in self.__status:
			return self.__status[YD_LASTFILES]
		else:
			return []

	def get_yd_lastdirs(self):
		if YD_LASTDIRS in self.__status:
			return self.__status[YD_LASTDIRS]
		else:
			return []
		
	def command(self, cmd:str, args:list=[]):
		__cli_cmd = [self.__cli, cmd]
		match cmd:
			case "setup":
				res = ""
			case ("start" | "stop" | "sync" | "-v"):
				try: 
					res = check_output(__cli_cmd).decode("utf-8")
				except CalledProcessError as e:
					res = e.output.decode("utf-8")
			case "status":
				try: 
					res = check_output(__cli_cmd).decode("utf-8")
				except CalledProcessError as e:
					res = e.output.decode("utf-8")
				self.__interpret_status(res)
			case "token":
				res = ""
			case "publish":
				res = ""
			case "unpublish":
				res = ""
			case _:
				raise InvalidYDCmd
		return res

	def __interpret_status(self, raw:str):
		self.__status = {}
		for l in raw.splitlines():
			if l == "":
				continue
			try:
				(key, value) = l.split(sep=":", maxsplit=1)
			except:
				(key, value) = (l, "")
			key = key.strip("\t").strip()
			value = value.strip("\t").strip().strip("'")
			if key in ["file", "directory"]:
				if key in self.__status:
					self.__status[key].append(value)
				else:
					self.__status[key] = [value]
			else:
				self.__status[key] = value
