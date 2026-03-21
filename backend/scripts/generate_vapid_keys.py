"""
Generate VAPID keys for Web Push.

Run once, then set the output as environment variables:
  VAPID_PRIVATE_KEY=<private key>
  VAPID_PUBLIC_KEY=<public key>
  VAPID_CLAIMS_EMAIL=mailto:your@email.com

Usage:
  python -m scripts.generate_vapid_keys
"""

from py_vapid import Vapid
import base64
import os


def main():
    vapid = Vapid()
    vapid.generate_keys()

    # Extract the raw bytes and encode as URL-safe base64
    raw_private = vapid.private_key.private_numbers().private_value.to_bytes(32, 'big')
    raw_public = vapid.public_key.public_bytes(
        encoding=__import__('cryptography.hazmat.primitives.serialization', fromlist=['Encoding']).Encoding.X962,
        format=__import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.UncompressedPoint,
    )

    private_b64 = base64.urlsafe_b64encode(raw_private).rstrip(b'=').decode('ascii')
    public_b64 = base64.urlsafe_b64encode(raw_public).rstrip(b'=').decode('ascii')

    print("=" * 60)
    print("VAPID Keys Generated — add these to your .env or Docker config:")
    print("=" * 60)
    print(f"VAPID_PRIVATE_KEY={private_b64}")
    print(f"VAPID_PUBLIC_KEY={public_b64}")
    print(f"VAPID_CLAIMS_EMAIL=mailto:your-email@example.com")
    print("=" * 60)
    print()
    print("The VAPID_PUBLIC_KEY is also given to the browser when subscribing.")
    print("Keep the VAPID_PRIVATE_KEY secret!")


if __name__ == "__main__":
    main()
