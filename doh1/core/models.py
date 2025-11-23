from django.db import models
import json

class Soldier(models.Model):
    personal_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, blank=True, default="Soldier")
    
    # changed: JSONField -> TextField to fix SQLite error
    _cookies_data = models.TextField(default="{}", blank=True)
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.personal_id

    # This 'getter' automatically converts the text back to a Dictionary
    # whenever you ask for soldier.cookies
    @property
    def cookies(self):
        try:
            return json.loads(self._cookies_data)
        except (ValueError, TypeError):
            return {}

    # This 'setter' automatically converts a Dictionary to text
    # whenever you save soldier.cookies = {...}
    @cookies.setter
    def cookies(self, value):
        self._cookies_data = json.dumps(value)