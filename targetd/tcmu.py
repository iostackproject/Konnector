# -*- coding: utf-8 -*-
# Copyright (c) 2015 MPSTOR Ltd. mpstor.com
from collections import defaultdict
import dbus
import logging as log
import os
import rtslib_fb as rtslib
import string
import subprocess
import time
from utils import TargetdError, invoke

GENERAL_TARGETD_ERROR = -1

def initialize(config_dict):
    return dict(
            create_filtered_volume=create_filtered_volume,
            delete_filtered_volume=delete_filtered_volume,
            )

def _check_setup(func):
    """Ensure configfs filesystem is mounted, save altered config.
    Also ensure the TCMU service is running.
    """
    def checker(*args, **kwargs):
        # This seems not to work on Ubuntu, so commented out.
        #subprocess.check_output('mount|grep -q configfs || '
        #        'mount -t configfs configfs /sys/kernel/config', shell=True)
        dbus.SystemBus().get_object('org.kernel.TCMUService1',
                '/org/kernel/TCMUService1')
        try:
            return func(*args, **kwargs)
        finally:
            try:
                rtslib.RTSRoot().save_to_file()
            except Exception, e:
                log.exception("error saving config")
    return checker

@_check_setup
def create_filtered_volume(req, handler=None, name=None, filters=None, device=None, serial=None):
    filters = filters or []
    handler = handler or "mp_filter_stack"
    if not name:
        raise TargetdError(GENERAL_TARGETD_ERROR, "No name specified.")
    err = _alnum(name, extras='_-')
    if err:
        raise TargetdError(GENERAL_TARGETD_ERROR, "%r: %s" % (name, err))
    if not (device or serial):
        raise TargetdError(GENERAL_TARGETD_ERROR, "No device specified.")
    if serial and not device:
        device = _device_from_serial(serial)
    if not device or not os.path.exists(device):
        raise TargetdError(GENERAL_TARGETD_ERROR, "Device not found.")

    _validate_filters(filters)
    filterstack = '>'.join(filters)
    if filterstack:
        filterstack += '>'
    config_str = handler + '/>' + filterstack + device
    filtered_dev = rtslib.UserBackedStorageObject(name, config=config_str,
            size=_device_size(device))
    log.debug("Created %s on %s" % (name, filterstack + device))
    tcm_loop = rtslib.FabricModule("loopback")
    target = rtslib.Target(tcm_loop)
    tpg = rtslib.TPG(target, 1)
    lun = rtslib.LUN(tpg, 0, filtered_dev)
    log.debug("Created loopback target %s on %s" % (target.wwn, name))
    for delay in range(1, 4):
        time.sleep(delay)
        dev = _device_from_wwn(filtered_dev.wwn)
        if dev:
            log.debug("Target %s is at %s" % (target.wwn, dev))
            return dev

@_check_setup
def delete_filtered_volume(req, name=None):
    if not name:
        raise TargetdError(GENERAL_TARGETD_ERROR, "No name specified.")
    root = rtslib.RTSRoot()
    stores = [obj for obj in root.storage_objects if obj.name == name
            and obj.plugin == 'user']
    if len(stores) != 1:
        raise TargetdError(GENERAL_TARGETD_ERROR,
                "%d backstores with name %r." % (len(stores), name))
    targets = {}
    for target in root.targets:
        for tpg in target.tpgs:
            for lun in tpg.luns:
                if lun.storage_object.name == name:
                    targets[target] = 1
    for target in targets.keys():
        log.debug("Deleting loopback target %s for %s." % (target.wwn, name))
        target.delete()
    log.debug("Deleting %s." % name)
    stores[0].delete()

def _alnum(name, extras=None, min_len=1, max_len=36):
    """Return a validation function that returns an error message unless
    its argument is a string within a defined length range containing
    only alphanumeric characters and any optional extra characters to be
    allowed.
    """
    if not isinstance(name, basestring):
        return "%r (%s) not a string" % (name, type(name))
    allowed = string.ascii_letters + string.digits + (extras or '')
    if not min_len <= len(name) <= max_len:
        return "must be between %d and %d characters long." % (
                min_len, max_len)
    invalid_chars = [char for char in name if char not in allowed]
    if invalid_chars:
        return "illegal character %r." % invalid_chars[0]

def _validate_filters(filters):
    for filt in filters:
        err = _alnum(filt, extras='_-')
        if err:
            raise TargetdError(GENERAL_TARGETD_ERROR, "%r: %s" % (filt, err))

SYS_BLOCK_DIR = "/sys/block"

def _device_from_wwn(wwn):
    """Find device from WWN (search VPD83 pages)."""
    all_devs = [dev for dev in os.listdir(SYS_BLOCK_DIR)
            if dev.startswith("sd")]
    for dev in all_devs:
        d = os.path.join(SYS_BLOCK_DIR, dev, "device")
        try:
            dev_ids = open(os.path.join(d, "vpd_pg83"), 'r').read()[4:]
        except IOError:
            continue
        if wwn in dev_ids:
            log.debug("device wwn %s found at %s" % (wwn, dev))
            return "/dev/" + dev
    log.debug("device wwn %s not found." % wwn)

def _device_from_serial(serial):
    """Find device from serial number (VPD80 page)."""
    all_devs = [dev for dev in os.listdir(SYS_BLOCK_DIR)
            if dev.startswith("sd")]
    for dev in all_devs:
        d = os.path.join(SYS_BLOCK_DIR, dev, "device")
        try:
            vpd80 = open(os.path.join(d, "vpd_pg80"), 'r').read()[4:]
        except IOError:
            continue
        if vpd80.replace('\x00','') == serial:
            log.debug("device serial %s found at %s" % (serial, dev))
            return "/dev/" + dev
    log.debug("device serial %s not found." % serial)

def _device_size(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        return os.lseek(fd, 0, os.SEEK_END)
    finally:
        os.close(fd)
