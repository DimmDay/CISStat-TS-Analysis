"""Operator-only admin notice diagnostics and safe transport test. No user proof."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("status", "deliver", "smtp-test"))
    args = p.parse_args()
    try:
        from apps.api.authentication.demo_admin_notifications import (
            status, publish_pending, recipient,
        )
        if args.command == "status":
            result = status()
        elif args.command == "deliver":
            result = publish_pending()
        else:
            from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery
            delivery = SmtpEmailDelivery.from_env()
            if delivery is None:
                raise ValueError()
            delivery.send(recipient(), "CISStat — проверка уведомлений администратору",
                          "Это проверка доставки уведомлений администратору.\n"
                          "Новый пользователь и демо-доступ не создавались.\n"
                          "Коды подтверждения и ссылки входа в это письмо не включаются.")
            result = {"ok": True, "smtp_accepted": True}
        print(json.dumps(result))
        return 1 if "error" in result else 0
    except Exception:  # Safe operator boundary; never print driver/SMTP response/PII.
        print('{"ok":false,"code":"demo_admin_unavailable"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
