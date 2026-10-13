import ctypes
libc = ctypes.CDLL(None)
buf = ctypes.create_string_buffer(16)
print(f"buf at {ctypes.addressof(buf):#x}")
libc.strcpy(buf, b"A" * 64)   # overflows the 16-byte buffer!
