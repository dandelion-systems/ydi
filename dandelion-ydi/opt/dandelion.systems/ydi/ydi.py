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
