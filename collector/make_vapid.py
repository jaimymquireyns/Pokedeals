"""Maakt een VAPID-sleutelpaar voor web-push. Eenmalig draaien: python make_vapid.py"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

key = ec.generate_private_key(ec.SECP256R1())
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print("=== PUBLIEKE sleutel (zet in docs/config.js bij VAPID_PUBLIC_KEY) ===")
print(base64.urlsafe_b64encode(pub).decode().rstrip("="))
print("\n=== PRIVÉ sleutel (zet als GitHub-secret VAPID_PRIVATE_KEY; deel deze met niemand) ===")
print(pem)
