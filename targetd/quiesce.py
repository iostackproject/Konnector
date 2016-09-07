# -*- coding: utf-8 -*-
# Copyright (c) 2015 MPSTOR Ltd. mpstor.com

import logging as log
import string
import subprocess
from utils import TargetdError

GENERAL_TARGETD_ERROR = -1

def initialize(config_dict):
    return dict(
            fswrites=fswrites,
            )

VIRSH_CMDS = {cmd: 'virsh qemu-agent-command \'%%s\' '
        '\'{"execute":"guest-fsfreeze-%s"}\'' % cmd
        for cmd in ("freeze", "thaw")}

def fswrites(req, domain=None, operation=None, timeout=15):
    """Quiesce or unquiesce filesystem writes by a VM (domain).
    operation is "freeze" (quiesce) or "thaw" (unquiesce);
    timeout is optional, with a default of 15:
    to ensure that a VM is not left in a frozen state, if
    operation is "freeze" then a thaw will issue timeout seconds
    after running this program -
    a timeout of 0 means "no timeout".
    """
    if not domain:
        raise TargetdError(GENERAL_TARGETD_ERROR,
                "Must specify a domain (VM).")
    if operation not in VIRSH_CMDS:
        raise TargetdError(GENERAL_TARGETD_ERROR,
                "Unsupported operation (%r)." % operation)
    cmd = VIRSH_CMDS[operation] % domain
    log.debug("fswrites: %s" % cmd)
    subp = subprocess.Popen(cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = subp.communicate()[0].strip()
    if subp.returncode:
        raise RuntimeError("%r returned %r: %r" % (cmd,
                subp.returncode, out))
    if operation == "freeze" and timeout != 0:
        thaw = VIRSH_CMDS["thaw"] % domain
        subprocess.Popen("sleep %s && %s" % (timeout, thaw), shell=True)
