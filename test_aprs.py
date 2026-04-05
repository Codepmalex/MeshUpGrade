import socket
import time

def test_login():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('rotate.aprs2.net', 14580))
        sock.send(f"user KE2BPN-15 pass 12345 vers MeshUpGrade 0.2.0 filter b/KD9XYZ-9\n".encode('utf-8'))
        
        login_resp = ""
        while "logresp" not in login_resp.lower() and "not allowed" in login_resp.lower():
            login_resp += sock.recv(1024).decode('utf-8')
            
        print("Final Login Resp:", login_resp)
        sock.close()
    except Exception as e:
        print("Error:", e)

test_login()
