"""Web-push versturen (pywebpush)."""
import json
import os
import tempfile


class WebPushSender:
    def __init__(self, private_pem, subject):
        # pywebpush leest de sleutel het liefst uit een bestand
        self._file = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
        self._file.write(private_pem.replace("\\n", "\n"))
        self._file.close()
        self.subject = subject

    def send(self, sub, payload):
        from pywebpush import WebPushException, webpush
        try:
            webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=json.dumps(payload), vapid_private_key=self._file.name, vapid_claims={"sub": self.subject})
            return "ok"
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            return "gone" if code in (404, 410) else "error"
        except Exception:
            return "error"

    def __del__(self):
        try:
            os.unlink(self._file.name)
        except Exception:
            pass
