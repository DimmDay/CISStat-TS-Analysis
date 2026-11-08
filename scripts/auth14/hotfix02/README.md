# AUTH-14 HOTFIX-02 — восстановить файл PELT из исходной поставки

08.11.2026, Москва. Наложить ZIP в корень checkout **поверх AUTH-14 и HOTFIX-01**, с заменой app/eda/structural_breaks.py. Карты/политики не перегенерируются: уже ожидают версию AUTH-14.

auth00(2).log установил точную причину: actual SHA-25604fa12257019e577989feb386798849132e975599c60af4c747f9caf819a51de совпадает с исходным файлом commit a16b31b. Expected285093ac3c96e1cf317db399fb2287658faae4d9c5546090d05877cfd357e76a совпадает с файлом первого выданного ZIP. То есть в рабочей папке оказалась базовая версия; причина её сохранения/возврата при локальных операциях не устанавливается по хешу. Это не расхождение CRLF: collector нормализует CRLF→LF.

Восстановленный файл взят побайтово из cisstat-auth14-a16b31b.zip, без дополнительного изменения научного алгоритма. Он содержит исходные AUTH-14 compute_kernel decorator и tick перед PELT fit. Регенерация inventory под старый файл скрыла бы пропущенную интеграцию metering. SHA указаны для нормализованных LF bytes; Get-FileHash для CRLF checkout может отличаться.

После распаковки, PowerShell из корня проекта:

```powershell
git add --pathspec-from-file=scripts/auth14/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Объединённый manifest включает AUTH-14, HOTFIX-01 и текущий патч. Затем можно повторить все default gates; commit/push выполняет тимлид. Gate остаётся строгим, auto-staging/regeneration нет. История/пользовательские изменения автоматически не сбрасываются.

Проверка: на отдельном worktree a16b31b+AUTH-14+HOTFIX-01 воспроизводится тот же WORKTREE failure при подстановке базового файла; затем накладывается этот ZIP, явно готовится INDEX и повторяется AUTH-00. Протоколы прилагаются. HTTP methods/paths/DTO, CU profile/version и scientific parameters не меняются относительно исходного AUTH-14. Новых migrations/dependencies нет. Дополнительных image changes к исходной AUTH-14 нет; первоначальные команды build api/web остаются в силе.
