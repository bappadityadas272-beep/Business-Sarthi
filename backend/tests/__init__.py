"""Test package. The in-process scheduler is switched off before the app is imported."""
import os

os.environ["SCHEDULER_ENABLED"] = "0"
