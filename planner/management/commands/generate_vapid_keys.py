import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Create the keys phone notifications need. Run once, then set the printed values on the server."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        public = vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.stdout.write("Add these environment variables in Render (Environment tab):\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(public)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(private)}")
        self.stdout.write("VAPID_SUBJECT=mailto:you@assumption.edu   (an email people can reach you at)")
        self.stdout.write("\nKeep VAPID_PRIVATE_KEY secret. Changing the keys turns off everyone's notifications.")
