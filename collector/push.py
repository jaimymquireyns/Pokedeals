"""Web-push versturen (pywebpush)."""
import json
import os
import tempfile


def normalize_pem(key):
    """De sleutel zoals hij in GitHub-secrets staat: met of zonder de BEGIN/END-regels, met echte of geschreven (\\n) regeleinden,
    met spaties. Geeft een geldige PEM terug."""
    body = key.replace("\\n", "\n").replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
    b64 = "".join(body.split())
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"


class WebPushSender:
    def __init__(self, private_pem, subject):
        # pywebpush leest de sleutel het liefst uit een bestand
        self._file = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
        self._file.write(normalize_pem(private_pem))
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
