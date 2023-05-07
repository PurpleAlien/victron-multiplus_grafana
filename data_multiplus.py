# This script reads some data from a Victron Multiplus-II inverter over VE.Bus
# and uses the MK3-USB interface.
# It for use with https://github.com/BarkinSpider/SolarShed/

import time
import sys, os, io
import struct
from struct import unpack

# For the MK3-USB interface 
import serial

sleepTime = 10

try:
    mk3 = serial.Serial('/dev/ttyUSB0')
    mk3.baudrate = 2400
    mk3.timeout  = 1
except:
    print("Victron MK3-USB not found.")

def readResult():
    # First byte is length and turn into int
    l = mk3.read(1)
    l = int.from_bytes(l, "big")
    # Read l+1 bytes, +1 for the checksum - both length itself and checksum are not counted
    data = mk3.read(l + 1)
    # Convert from bytes to bytearray
    data = bytearray(data)
    # Reattach length for checksum calculation    
    data.append(l)
    # Check checksum
    if sum([x for x in data])%256 != 0:
        raise Exception("Checksum failed")

    return data

def makeMK3Command(command):
        # Convert to bytearray
        command = bytearray.fromhex(command)
        # add 1 byte for the checksum
        length = len(command) + 1
        # First byte is length, second 0xFF
        buf = [length, 0xFF]
        # Add the command to the buffer
        buf.extend(command)
        # Calcuate checksum and add
        checksum = 256 - sum([x for x in buf])%256
        buf.append(checksum)

        return buf

def sendMK3Command(command):
    # Add length, checksum, etc
    c = makeMK3Command(command)
    # Write to the Multiplus
    mk3.write(c)
    # Read all the data coming back
    while True:
        data = readResult()
        if data[0] != 0xFF or data[1] != 0x56: # 0x56 == 'V'
            break
    return data

# Scaling factor - page 18 of victron-interfacing-mk2-protocol-3.12.pdf
def scalefunc(factor):
    s = abs(factor)
    if s >= 0x4000:
        return 1.0/(0x8000 - s)
    return s
   
def initMK3():        
        # Read the version data. The Multiplus keeps broadcasting this. 
        # Explicitely reading it stops this for a while.
        # V command == 0x56 in hex        
        mk3.write(makeMK3Command('56'))
        time.sleep(0.5)
        mk3.reset_input_buffer()   
        
        # We need to tell the MK-3 to set the address to something else than the default 0xFF
        for i in range(0, 3):
            try:
                # A command == 0x41 in hex
                sendMK3Command('41 01 00') # Address 0x00 will do, 0x01 to indicate a write
            except (ValueError, struct_error):
                pass
            else:
                break
         
def readMultiplus(fileObj):

    try:

        # Clear the buffer 
        mk3.reset_input_buffer()

        # Inverter Voltage scale and offset, 'W' command == 0x57 in hex
        data = sendMK3Command('57 36 02 00')
        scale, ignore, offset = unpack('<h B h', data[3:8])

        # Clear the buffer 
        mk3.reset_input_buffer()

        # Actual AC voltage and current, 'F' command == 0x46 in hex, frame type 1
        data = sendMK3Command('46 01')        
        uinv, iinv = unpack('<H h', data[10:14]) # Inverter voltage and current
        bf, invf = unpack('<B B', data[1:3])     # BF factor and Inverter Factor
       
        AC_voltage = (uinv + offset) * scalefunc(scale) * bf

        # Clear the buffer 
        mk3.reset_input_buffer()
        
        # Inverter Current scale and offset, 'W' command == 0x57 in hex
        data = sendMK3Command('57 36 03 00')       
        scale, ignore, offset = unpack('<h B h', data[3:8])
        
        AC_current = (iinv + offset) * scalefunc(scale) * invf     

        # Clear the buffer 
        mk3.reset_input_buffer()

        # DC voltage and current,  'F' command == 0x46 in hex, frame type 0
        data = sendMK3Command('46 00')
        DC_voltage = unpack('<H', data[6:8])[0]
        DC_current = unpack('<i', data[8:11] + (bytes.fromhex('00') if data[10] < 0x80 else bytes.fromhex('FF')))[0] # DC current fields are unsigned 24-bit values.
        
        # Clear the buffer
        mk3.reset_input_buffer()
 
        # The DC voltage scale and offset values, 'W' command == 0x57 in hex
        data = sendMK3Command('57 36 04 00')
        scale, ignore, offset = unpack('<h B h', data[3:8])
        
        # Apply
        DC_voltage = (DC_voltage + offset) * scalefunc(scale)

        # Clear the buffer
        mk3.reset_input_buffer()

        # The DC current scale and offset values, 'W' command == 0x57 in hex
        data = sendMK3Command('57 36 05 00')
        scale, ignore, offset = unpack('<h B h', data[3:8])

        # Apply
        DC_current = (DC_current + offset) * scalefunc(scale)
        
        # Write the DC values to the output fileobject

        valName  = "mode=\"batVolts\""
        valName  = "{" + valName + "}"
        dataStr  = f"MULTIPLUS_INV{valName} {DC_voltage}"
        print(dataStr, file=fileObj)

        valName  = "mode=\"batAmps\""
        valName  = "{" + valName + "}"
        dataStr  = f"MULTIPLUS_INV{valName} {DC_current}"
        print(dataStr, file=fileObj)

        # Not sure of using the AC voltage and current - something seems wrong
        # Use DC voltage and current instead (for now)
        # Combine the DC voltage and current to Watt
        valName  = "mode=\"outputW\""
        valName  = "{" + valName + "}"
        dataStr  = f"MULTIPLUS_INV{valName} {DC_voltage * DC_current}"
        print(dataStr, file=fileObj) 
        
    except Exception as e :
        raise Exception(e)
        #print(e)   

# Initialize MK3 interface, setting address
initMK3()

while True:
    file_object = open('/ramdisk/VICTRON_MULTIPLUS.prom.tmp', mode='w')
    try: 
        readMultiplus(file_object)
        file_object.flush()
        file_object.close()
        outLine = os.system('/bin/mv /ramdisk/VICTRON_MULTIPLUS.prom.tmp /ramdisk/VICTRON_MULTIPLUS.prom')
    except Exception as e :
        print(e)
        file_object.close()
    
    time.sleep(sleepTime)

