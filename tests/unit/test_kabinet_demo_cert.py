"""Independent deployment/acceptance oracles for the seven UI demo tasks."""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class KabinetDemoCertification(unittest.TestCase):
    def test_compose_forwards_public_pair_at_build_time(self):
        web = yaml.safe_load(
            (ROOT / "deployment/cisstat-stack/docker-compose.yml").read_text(
                encoding="utf-8-sig"
            )
        )["services"]["web"]
        for name in ("NEXT_PUBLIC_DEMO_LOGIN", "NEXT_PUBLIC_DEMO_PASSWORD"):
            self.assertEqual(
                web["build"].get("args", {}).get(name), "${" + name + ":-}"
            )
            self.assertNotIn(name, web["environment"])
        docker = (ROOT / "apps/standalone/Dockerfile").read_text(encoding="utf-8-sig")
        build = docker.split("FROM node:22-bookworm-slim\n")[0]
        for name in ("NEXT_PUBLIC_DEMO_LOGIN", "NEXT_PUBLIC_DEMO_PASSWORD"):
            self.assertRegex(build, r"(?m)^ARG " + name + r"(?:=)?$")
            self.assertRegex(build, r"(?m)^ENV " + name + r"=\$\{" + name + r"\}$")
        self.assertLess(
            build.index("ARG NEXT_PUBLIC_DEMO_LOGIN"),
            build.index("RUN npm run build --workspace="),
        )

    def test_public_env_example_defaults_blank(self):
        text = (ROOT / "deployment/cisstat-stack/.env.example").read_text(
            encoding="utf-8-sig"
        )
        for name in ("NEXT_PUBLIC_DEMO_LOGIN", "NEXT_PUBLIC_DEMO_PASSWORD"):
            self.assertRegex(text, r"(?m)^" + name + r"=$")

    def test_retention_is_not_an_access_extension(self):
        text = (ROOT / "packages/ui/components/DemoLanding.tsx").read_text(
            encoding="utf-8-sig"
        )
        text = re.sub(r"\s+", " ", text).casefold()
        self.assertNotRegex(text, r"после окончания демо результаты\s+доступны")
        self.assertIn("после окончания демо доступ закрывается", text)

    def test_both_shells_metadata_and_pivot_surface(self):
        for shell in ("embedded", "standalone"):
            text = (ROOT / f"apps/{shell}/app/demo/page.tsx").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn("DemoLanding", text)
            self.assertRegex(text, r"robots:\s*\{\s*index:\s*true,\s*follow:\s*true")
            self.assertIn("no-referrer", text)
            for page in ("login", "account"):
                self.assertIn(
                    "false",
                    (ROOT / f"apps/{shell}/app/{page}/page.tsx").read_text(
                        encoding="utf-8-sig"
                    ),
                )
        pivot = (ROOT / "apps/standalone/app/dashboard/page.tsx").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("DashboardPivot", pivot)
        self.assertIn("index: false", pivot)
        self.assertIn("no-referrer", pivot)

    def test_original_manifest_complete_and_safe(self):
        names = (
            (ROOT / "scripts/kabinet_demo/files.txt")
            .read_text(encoding="utf-8-sig")
            .splitlines()
        )
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn("..", Path(name).parts)
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertIn("apps/standalone/app/dashboard/page.tsx", names)
        self.assertIn("scripts/kabinet_demo/files.txt", names)


class SourceEncodingTests(unittest.TestCase):
    def test_oracles_use_utf8_even_when_windows_default_is_cp1251(self):
        import io
        from unittest.mock import patch

        original = Path.read_text

        def windows_read(path, encoding=None, errors=None):
            return original(path, encoding=encoding or "cp1251", errors=errors)

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            KabinetDemoCertification
        )
        with patch.object(Path, "read_text", windows_read):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertEqual(result.testsRun, 5)
        self.assertFalse(result.skipped)
        self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))

    def test_utf8_bom_crlf_checkout_preserves_checks_and_detects_content_change(self):
        import io
        import tempfile
        from unittest.mock import patch

        names = set(
            (ROOT / "scripts/kabinet_demo/files.txt")
            .read_text(encoding="utf-8-sig")
            .splitlines()
        )
        names.update(
            {
                "deployment/cisstat-stack/docker-compose.yml",
                "deployment/cisstat-stack/.env.example",
                "apps/standalone/Dockerfile",
                "packages/ui/components/DemoLanding.tsx",
                "apps/standalone/app/dashboard/page.tsx",
            }
        )
        for shell in ("embedded", "standalone"):
            for page in ("demo", "login", "account"):
                names.add(f"apps/{shell}/app/{page}/page.tsx")
        with tempfile.TemporaryDirectory(
            prefix="kabinet-encoding-", dir=ROOT.parent
        ) as folder:
            target = Path(folder)
            for name in names:
                text = (ROOT / name).read_text(encoding="utf-8-sig")
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    b"\xef\xbb\xbf"
                    + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
                )
            with patch(__name__ + ".ROOT", target):
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                    KabinetDemoCertification
                )
                result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                self.assertEqual(result.testsRun, 5)
                self.assertFalse(result.skipped)
                self.assertTrue(
                    result.wasSuccessful(), str(result.errors + result.failures)
                )
                path = target / "packages/ui/components/DemoLanding.tsx"
                text = path.read_text(encoding="utf-8-sig")
                changed = re.sub(r"доступ\s+закрывается", "доступ продлевается", text)
                self.assertNotEqual(changed, text)
                path.write_bytes(changed.encode("utf-8"))
                failed = unittest.TextTestRunner(stream=io.StringIO()).run(
                    KabinetDemoCertification(
                        "test_retention_is_not_an_access_extension"
                    )
                )
                self.assertFalse(
                    failed.wasSuccessful(), "Semantic drift must still fail"
                )


if __name__ == "__main__":
    unittest.main()
