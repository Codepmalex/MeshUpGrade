import time
t = time.gmtime()
time_str = f"{t.tm_mday:02d}{t.tm_hour:02d}{t.tm_min:02d}z"
print(f"Timestamp str: {time_str}")
