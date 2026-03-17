import socket
import ipaddress
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except:
        return '127.0.0.1'
    finally:
        s.close()
        
local_ip = get_local_ip()
network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
print(f"Sweeping network: {network} from local IP: {local_ip}")

def check_ip(ip):
    ip_str = str(ip)
    if ip_str == local_ip: return None
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            result = s.connect_ex((ip_str, 4403))
            if result == 0:
                return ip_str
        except Exception as e:
            pass
    return None

start = time.time()
found = []
opts = list(network.hosts())
print(f"Checking {len(opts)} IPs...")
with ThreadPoolExecutor(max_workers=50) as executor:
    futures = [executor.submit(check_ip, ip) for ip in opts]
    for i, future in enumerate(as_completed(futures)):
        res = future.result()
        if res:
            print(f"FOUND: {res}")
            found.append(res)
        if i % 50 == 0 and i > 0:
            print(f"  ...checked {i} so far...")

print(f"Done in {time.time() - start:.2f}s. Found {len(found)}: {found}")
