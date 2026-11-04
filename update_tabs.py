#!/usr/bin/python3 -I
import os,sys
os.execv('/usr/bin/python3',['/usr/bin/python3','-I','/usr/local/libexec/bizon-tabs-update']+sys.argv[1:])
