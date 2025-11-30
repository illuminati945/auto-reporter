from django.db import models
import json

class Soldier(models.Model):
    personal_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, blank=True, default="Soldier")
    
    # Storage Fields (Text-based JSON)
    _cookies_data = models.TextField(default="{}", blank=True)
    _local_storage_data = models.TextField(default="{}", blank=True)
    _session_storage_data = models.TextField(default="{}", blank=True)
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.personal_id

    # --- Cookies Property ---
    @property
    def cookies(self):
        try: return json.loads(self._cookies_data)
        except (ValueError, TypeError): return {}

    @cookies.setter
    def cookies(self, value):
        self._cookies_data = json.dumps(value)

    # --- Local Storage Property ---
    @property
    def local_storage(self):
        try: return json.loads(self._local_storage_data)
        except (ValueError, TypeError): return {}

    @local_storage.setter
    def local_storage(self, value):
        self._local_storage_data = json.dumps(value)

    # --- Session Storage Property ---
    @property
    def session_storage(self):
        try: return json.loads(self._session_storage_data)
        except (ValueError, TypeError): return {}

    @session_storage.setter
    def session_storage(self, value):
        self._session_storage_data = json.dumps(value)