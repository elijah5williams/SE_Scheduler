from django.core.management.base import BaseCommand

from planner.push import generate_keys


class Command(BaseCommand):
    help = (
        "Optional: print a new pair of notification keys. The server already creates its own "
        "automatically; use this only if you want to set VAPID_* environment variables yourself."
    )

    def handle(self, *args, **options):
        public, private = generate_keys()
        self.stdout.write("Optional. The server makes its own keys if these aren't set.\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={private}")
        self.stdout.write("VAPID_SUBJECT=mailto:you@assumption.edu")
        self.stdout.write("\nKeep VAPID_PRIVATE_KEY secret. Changing the keys turns off everyone's notifications.")
