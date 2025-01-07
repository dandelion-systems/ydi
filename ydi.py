from sys import exc_info

from yd_appind import YDIndicator
from yd_cli import YandexDisk		

def main():
	theDisk = YandexDisk()
	theIndicator = YDIndicator(theDisk)

if __name__ == "__main__":
	try:
		main()
	except:
		print(exc_info())
