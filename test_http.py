import requests

payload = "user KE2BPN-13 pass 12345 vers MeshUpGrade 0.2.0\r\nKE2BPN-5>APRS,TCPIP*:=4300.58N/07837.90WbHTTP TEST\r\n"
url = "http://rotate.aprs2.net:8080/"

try:
    resp = requests.post(url, data=payload, headers={"Content-Type": "application/octet-stream"}, timeout=5)
    print("Status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print(e)
