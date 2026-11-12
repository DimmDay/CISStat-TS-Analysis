# AUTH24 - Wallet

После деплоя: до провижининга кошелька платформа ведёт себя как прежде (WalletPanel скрыта по wallet_required); после manage_wallet.py create-wallet OWNER видит «Аккаунт → Баланс CU» с журналом и возвратами, MEMBER — только остаток. Откат — предыдущие образы api/web, БД задача не меняет.