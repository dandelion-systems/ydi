#!/bin/bash

# This file is part of Yandex Disk indicator and control (YDI).
# 
# Copyright 2025 Dandelion Systems <dandelion.systems@gmail.com>
# 
# YDI is free software; you can redistribute it and/or modify
# it under the terms of the MIT License.
# 
# YDI is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. 
# See the MIT License for more details.
# 
# SPDX-License-Identifier: MIT

# Keeps yandex-disk daemon alive if it goes into 'paused' state.
# This is usually the case when the computer suspends on power settings.

set -u

function yd_status_contains() {
	for x in $1; do
		if [ "$x" = "$2" ]; then
			return 0
		fi
	done
	return 1
}

yd_valid_status="idle index busy"

yd_status=$(yandex-disk status | awk '/Synchronization core status/{print $4}')

if yd_status_contains "$yd_valid_status" "$yd_status"; then
	echo "Yandex Disk daemon is running. Status is $yd_status."
else
	echo "Yandex Disk is not running, needs a restart. Attempting now."
	yandex-disk stop 2> /dev/null
	yandex-disk start
fi

