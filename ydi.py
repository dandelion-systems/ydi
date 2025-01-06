import sys

from yd_appind import YDIndicator
from yd_cli import YandexDisk		

def main():
	#options()
	theDisk = YandexDisk()
	theIndicator = YDIndicator(theDisk)


if __name__ == "__main__":
	try:
		main()
	except:
		print(sys.exc_info())
