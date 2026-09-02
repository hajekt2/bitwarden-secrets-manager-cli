#!/bin/sh
# Compatibility entry point: reject before looking up any credential.
printf '%s\n' 'Operation denied. Secret listing and generic secret injection are disabled.' >&2
exit 2
