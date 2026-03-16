try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
    print("zeroconf installed")
except ImportError:
    print("zeroconf NOT installed")
