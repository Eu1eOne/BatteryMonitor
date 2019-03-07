# *****BatteryMonitor main file batteries.py*****
# Copyright (C) 2014 Simon Richard Matthews
# Project loaction https://github.com/simat/BatteryMonitor
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


#!/usr/bin/python
import sys
import time
import serial
import binascii
import glob
from config import config
numcells = config['battery']['numcells']
import logger
log = logger.logging.getLogger(__name__)
log.setLevel(logger.logging.DEBUG)
log.addHandler(logger.errfile)
initrawdat ={'DataValid':False,'BInI':0.0,'BOutI':0.0,'BV':0.0,'PVI':0.0,'PVW':0,'ACW':0.0,'ChgStat':b'00'}



class Rawdat():
  """class for obtaining data from and controlling indidvdual PIP inverters.
  When class is instantiated the SN of the PIP is used to tie the instance of
  the class to the particular machine"""

  def __init__(self,sn):
    self.rawdat = dict.copy(initrawdat)
    self.reply ='' # placeholder for reply from sendcmd
    self.pipdown=0.0
    self.sn=sn
    try:
      self.findpip()
    except serial.serialutil.SerialException as err:
      self.pipdown=time.time() # flag pip is down
      log.error(err)


    self.stashok=False
    self.floatv=48.0
    self.bulkv=48.0
    self.rechargev=48.0
    self.lowv=44.0
    self.stashok=False
    self.command=b''  # last command sent to PIP

  def findpip(self):
    """Scan ports to find PIP port"""

    self.pipport=""
    for dev in glob.glob(config['Ports']['pipport']):
      for i in range(2):
        try:
          self.openpip(dev)
          self.sendcmd("QID",18)
          if self.reply[1:15].decode('ascii','strict')==str(self.sn):
            self.pipport=dev
            break
        except serial.serialutil.SerialException:
          pass
        finally:
          self.port.close
      if self.pipport!="":
        break
    if self.pipport=="":
      raise serial.serialutil.SerialException("Couldn't find PIP sn {}".format(self.sn))

  def openpip(self,port):
    self.port = serial.Serial(port,baudrate=2400,timeout=1)  # open serial port

  def crccalc(self,command):
    """returns crc as integer from binary string command"""

    crc=binascii.crc_hqx(command,0)
    crchi=crc>>8
    crclo=crc&255

    if crchi == 0x28 or crchi==0x0d or crchi==0x0a:
      crc+=256

    if crclo == 0x28 or crclo==0x0d or crclo==0x0a:
      crc+=1
    return crc

  def sendcmd(self,command,replylen):
    """send command/query to Pip4048, return reply"""
    self.command=command.encode('ascii','strict')
    crc=self.crccalc(self.command)
    self.command=self.command+crc.to_bytes(2, byteorder='big')+b'\r'
#    self.port.reset_input_buffer()
    self.port.flushInput()
    self.port.write(self.command)
    self.reply = self.port.read(replylen)
    if self.crccalc(self.reply[0:-3]) != int.from_bytes(self.reply[-3:-1],byteorder='big'):
      raise serial.serialutil.SerialException('CRC error in reply')

  def sendQ1(self):  #special to send Q1 command due to variable length reply
    try:
      self.sendcmd('Q1',74)
    except serial.serialutil.SerialException:
      if self.reply[-2:-1]!=b'\r': # check for different length self.reply
        self.reply=self.reply+self.port.read(17)

  def setparam(self,command):
#    time.sleep(5.0)
    self.sendcmd(command,7)
    if self.reply[1:4]!=b'ACK':
#      raise serial.serialutil.SerialException('Bad Parameters')
       log.error('Bad Reply {} to command {}'.format(self.reply,command))


  def opensetparam(self,command):
    """open port, send set parameter command to pip, close port"""
    self.openpip(self.pipport)
    self.setparam(command)
    self.port.close

  def setparamnoerror(self,command): # set parameter, ignore errors
    try:
      self.opensetparam(command)
    except serial.serialutil.SerialException:
      pass

  def getdata(self):
    """returns dictionary with data from Pip4048"""
#    log.debug('open')
    self.rawdat = dict.copy(initrawdat)
    if self.pipdown==0.0:
      for i in range(5):
        try:
          self.openpip(self.pipport)
          self.sendcmd('QPIGS',110)
          self.rawdat['BInI']=float(self.reply[47:50].decode('ascii','strict'))
          self.rawdat['BOutI']=float(self.reply[77:82].decode('ascii','strict'))
          self.rawdat['PVI']=float(self.reply[60:64].decode('ascii','strict'))
          self.rawdat['BV']=float(self.reply[41:46].decode('ascii','strict'))
          self.rawdat['ACW']=float(self.reply[28:32].decode('ascii','strict'))
          self.sendQ1()
          self.rawdat['ChgStat']=self.reply[69:71]
          self.rawdat['PVW']=float(self.reply[53:56].decode('ascii','strict'))
          self.rawdat['ibat']=self.rawdat['BOutI']-self.rawdat['BInI']
          self.rawdat['ipv']=-self.rawdat['PVI']
          self.rawdat['iload']=self.rawdat['ibat']-self.rawdat['ipv']
          self.rawdat['DataValid']=True
          break
        except ValueError as err:
          log.error('PIP bad response{} to command {}'.format(self.reply,self.command))
          time.sleep(0.5)
          if i==4:
            self.pipdown=time.time() # flag pip is down
            log.error("PIP sn {} interface down".format(self.sn))
        except serial.serialutil.SerialException as err:
          log.error('PIP interface error {}'.format(err))
          time.sleep(0.5)
          if i==4:
            self.pipdown=time.time() # flag pip is down
            log.error("PIP sn {} interface down".format(self.sn))
        finally:
          self.port.close()
    else:
      downtime=time.time()-self.pipdown
      if downtime%600<config['sampling']['sampletime']: #retry interface every 10 minutes
        try:
          self.findpip()
        except serial.serialutil.SerialException:
          pass
#          if downtime>3600: # upgrade error if more than one hour
#            raise
        else:
          self.pipdown=0.0
          log.info("PIP sn {} interface back up".format(self.sn))
