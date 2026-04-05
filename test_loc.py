import time
lat_str = "4042.77N"
icon_class = "/"
lon_str = "07400.36W"
icon_id = "b"
t = time.gmtime()
time_str = f"{t.tm_mday:02d}{t.tm_hour:02d}{t.tm_min:02d}z"
aprs_pkt = f"KD9XYZ-9>APRS,TCPIP*:@" + time_str + f"{lat_str}{icon_class}{lon_str}{icon_id}HAM licensed node. MeshUpGrade (Github!)\r\n"
print("Generated:", repr(aprs_pkt))
