"""Run once on the server; store the private key only in hosting environment secrets."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

def b64(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')
if __name__=='__main__':
    key=ec.generate_private_key(ec.SECP256R1())
    print('VAPID_PRIVATE_KEY='+b64(key.private_numbers().private_value.to_bytes(32,'big')))
    print('VAPID_PUBLIC_KEY='+b64(key.public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint)))
    print('VAPID_SUBJECT=mailto:YOUR_CONTACT_EMAIL')
