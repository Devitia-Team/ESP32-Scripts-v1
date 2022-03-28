esptool.py --port com3 erase_flash
esptool.py --chip esp32 --port com3 write_flash -z 0x1000 esp32-20220117-v1.18.bin